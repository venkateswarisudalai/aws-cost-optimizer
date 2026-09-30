"""Detect incomplete S3 multipart uploads that quietly bill storage forever.

When a multipart upload is started but never completed or aborted, the parts
already uploaded keep sitting in the bucket — billed at the normal storage rate
but invisible in the S3 console object listing. There is no built-in expiry
unless the bucket has an `AbortIncompleteMultipartUpload` lifecycle rule, so on
long-lived buckets this is one of the most common silent cost leaks.

This is an account-wide check: `list_buckets` is global, and each bucket is
inspected in its own home region. The scanner runs it once (GLOBAL) rather than
per region, so findings aren't duplicated.

Read-only: uses ListAllMyBuckets, GetBucketLocation, ListBucketMultipartUploads
and ListMultipartUploadParts only. It never aborts or deletes anything — the
fix is surfaced as a copy-paste command for the user to run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import S3_STANDARD_GB_MONTH

CHECK_ID = "s3.incomplete-multipart-upload"
GLOBAL = True  # account-wide; scanner runs this once, not per region

# Only count uploads older than this — a younger one may still be in progress.
MIN_AGE_DAYS = 7
# Don't size more than this many stale uploads per bucket (each needs a
# list_parts call); beyond it we note truncation rather than hammer the API.
MAX_UPLOADS_SIZED_PER_BUCKET = 500
# Skip buckets whose orphaned data is below this — not worth the noise.
MIN_SAVINGS_USD = 0.01

_IGNORABLE = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "AllAccessDisabled",
    "NoSuchBucket",
}


def _bucket_region(s3, bucket: str) -> str | None:
    """Resolve a bucket's home region (LocationConstraint quirks included)."""
    try:
        loc = s3.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    except ClientError as e:
        if e.response["Error"]["Code"] in _IGNORABLE:
            return None
        raise
    # us-east-1 reports None/""; the legacy "EU" alias means eu-west-1.
    if not loc:
        return "us-east-1"
    if loc == "EU":
        return "eu-west-1"
    return loc


def _stale_upload_bytes(s3r, bucket: str, cutoff: datetime) -> tuple[float, int, bool]:
    """Sum the part bytes of incomplete uploads older than `cutoff`.

    Returns (total_bytes, stale_upload_count, truncated).
    """
    total_bytes = 0.0
    stale = 0
    sized = 0
    truncated = False

    paginator = s3r.get_paginator("list_multipart_uploads")
    for page in paginator.paginate(Bucket=bucket):
        for up in page.get("Uploads", []):
            initiated = up.get("Initiated")
            if initiated is not None and initiated > cutoff:
                continue  # too new — might still be uploading
            stale += 1
            if sized >= MAX_UPLOADS_SIZED_PER_BUCKET:
                truncated = True
                continue
            sized += 1
            try:
                part_pages = s3r.get_paginator("list_parts").paginate(
                    Bucket=bucket, Key=up["Key"], UploadId=up["UploadId"]
                )
                for pp in part_pages:
                    for part in pp.get("Parts", []):
                        total_bytes += part.get("Size", 0)
            except ClientError as e:
                if e.response["Error"]["Code"] in _IGNORABLE:
                    continue
                raise
    return total_bytes, stale, truncated


def _existing_lifecycle_rules(s3r, bucket: str) -> int | None:
    """How many lifecycle rules the bucket already has (None = couldn't check).

    put-bucket-lifecycle-configuration REPLACES the whole configuration, so the
    one-line fix is only safe on a bucket with no rules yet."""
    try:
        return len(s3r.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", []))
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
            return 0
        return None


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    # list_buckets is global; us-east-1 endpoint is fine.
    s3 = client("s3", "us-east-1", profile)
    findings: list[Finding] = []

    try:
        buckets = s3.list_buckets().get("Buckets", [])
    except ClientError as e:
        if e.response["Error"]["Code"] in _IGNORABLE:
            return []
        raise

    cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)

    for b in buckets:
        bucket = b["Name"]
        bregion = _bucket_region(s3, bucket)
        if bregion is None:
            continue

        s3r = client("s3", bregion, profile)
        try:
            total_bytes, stale_count, truncated = _stale_upload_bytes(
                s3r, bucket, cutoff
            )
        except ClientError as e:
            if e.response["Error"]["Code"] in _IGNORABLE:
                continue
            raise

        if stale_count == 0:
            continue

        stored_gb = total_bytes / (1024 ** 3)
        monthly = round(stored_gb * S3_STANDARD_GB_MONTH, 2)
        if monthly < MIN_SAVINGS_USD:
            continue

        arn = f"arn:aws:s3:::{bucket}"
        existing_rules = _existing_lifecycle_rules(s3r, bucket)
        abort_rule = (
            '{"ID":"abort-incomplete-mpu","Status":"Enabled","Filter":{},'
            '"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}'
        )
        if existing_rules == 0:
            fix = (
                f"aws s3api put-bucket-lifecycle-configuration --region {bregion} "
                f"--bucket {bucket} --lifecycle-configuration '{{\"Rules\":[{abort_rule}]}}'  "
                "# bucket has no lifecycle rules yet, so nothing is replaced"
            )
        else:
            # Merge into the existing rules instead of overwriting them.
            fix = (
                f"aws s3api get-bucket-lifecycle-configuration --region {bregion} "
                f"--bucket {bucket} > lifecycle.json\n"
                f"# Add this rule to the Rules list in lifecycle.json: {abort_rule}\n"
                f"aws s3api put-bucket-lifecycle-configuration --region {bregion} "
                f"--bucket {bucket} --lifecycle-configuration file://lifecycle.json"
            )
        sized_note = (
            f" (sized the first {MAX_UPLOADS_SIZED_PER_BUCKET}; real total is higher)"
            if truncated
            else ""
        )

        findings.append(
            Finding(
                id=Finding.make_id(CHECK_ID, arn),
                check_id=CHECK_ID,
                title=(
                    f"{stale_count} incomplete multipart upload(s) in '{bucket}' "
                    f"(~{stored_gb:.2f} GB orphaned)"
                ),
                description=(
                    f"Bucket '{bucket}' has {stale_count} multipart upload(s) older than "
                    f"{MIN_AGE_DAYS} days that were never completed or aborted{sized_note}. "
                    "The uploaded parts keep billing storage but don't show up as objects. "
                    "Abort them, and add a lifecycle rule so it can't recur."
                ),
                service="s3",
                region=bregion,
                resource_arn=arn,
                resource_id=bucket,
                monthly_savings_usd=monthly,
                severity=Severity.from_monthly_usd(monthly),
                confidence=Confidence.HIGH,  # parts are unambiguously orphaned
                cli_fix_command=fix,
                # Overwriting existing rules would silently drop expiry/tiering.
                fix_destructive=existing_rules != 0,
                evidence={
                    "bucket": bucket,
                    "stale_upload_count": stale_count,
                    "orphaned_bytes": int(total_bytes),
                    "orphaned_gb": round(stored_gb, 3),
                    "min_age_days": MIN_AGE_DAYS,
                    "truncated": truncated,
                    "existing_lifecycle_rules": existing_rules,
                },
            )
        )

    return findings
