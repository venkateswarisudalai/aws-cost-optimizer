"""Detect EBS snapshots older than 90 days owned by this account."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import EBS_SNAPSHOT_GB_MONTH

CHECK_ID = "ebs.snapshot-old"
AGE_THRESHOLD_DAYS = 90


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    findings: list[Finding] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=AGE_THRESHOLD_DAYS)

    try:
        paginator = ec2.get_paginator("describe_snapshots")
        pages = paginator.paginate(OwnerIds=[account_id])
        for page in pages:
            for snap in page["Snapshots"]:
                start_time = snap["StartTime"]
                if start_time > cutoff:
                    continue

                size_gb = snap["VolumeSize"]
                monthly = round(EBS_SNAPSHOT_GB_MONTH * size_gb, 2)
                snap_id = snap["SnapshotId"]
                arn = f"arn:aws:ec2:{region}::snapshot/{snap_id}"
                age_days = (datetime.now(timezone.utc) - start_time).days

                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Old EBS snapshot {snap_id} ({age_days}d old, {size_gb} GB)",
                        description=(
                            f"Snapshot is {age_days} days old. If you keep daily snapshots "
                            "via a lifecycle policy, remove this manual one. Verify it's "
                            "not the backup of record before deleting."
                        ),
                        service="ec2",
                        region=region,
                        resource_arn=arn,
                        resource_id=snap_id,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.MEDIUM,  # might be intentional backup
                        cli_fix_command=(
                            f"aws ec2 delete-snapshot --region {region} --snapshot-id {snap_id}"
                        ),
                        fix_destructive=True,
                        evidence={
                            "size_gb": size_gb,
                            "age_days": age_days,
                            "start_time": start_time.isoformat(),
                            "description": snap.get("Description", ""),
                            "volume_id": snap.get("VolumeId", ""),
                            "tags": {t["Key"]: t["Value"] for t in snap.get("Tags", [])},
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
