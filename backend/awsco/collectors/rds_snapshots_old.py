"""Detect manual RDS DB snapshots older than 90 days.

Automated snapshots expire on their own; *manual* ones live forever and quietly
accrue backup-storage charges. This is the RDS analogue of `ebs.snapshot-old`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import RDS_SNAPSHOT_GB_MONTH

CHECK_ID = "rds.snapshot-old"
AGE_THRESHOLD_DAYS = 90


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    rds = client("rds", region, profile)
    findings: list[Finding] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=AGE_THRESHOLD_DAYS)

    try:
        paginator = rds.get_paginator("describe_db_snapshots")
        # Only manual snapshots — automated ones are managed by the retention window.
        for page in paginator.paginate(SnapshotType="manual"):
            for snap in page["DBSnapshots"]:
                created = snap.get("SnapshotCreateTime")
                if created is None or created > cutoff:
                    continue

                size_gb = snap.get("AllocatedStorage", 0)
                monthly = round(RDS_SNAPSHOT_GB_MONTH * size_gb, 2)
                snap_id = snap["DBSnapshotIdentifier"]
                arn = snap.get(
                    "DBSnapshotArn",
                    f"arn:aws:rds:{region}:{account_id}:snapshot:{snap_id}",
                )
                age_days = (datetime.now(timezone.utc) - created).days

                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=(
                            f"Old manual RDS snapshot {snap_id} "
                            f"({age_days}d old, {size_gb} GB)"
                        ),
                        description=(
                            f"Manual DB snapshot is {age_days} days old and still billing "
                            "backup storage. If it's not your backup of record, delete it. "
                            "Verify before deleting — snapshots are not recoverable."
                        ),
                        service="rds",
                        region=region,
                        resource_arn=arn,
                        resource_id=snap_id,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.MEDIUM,  # might be an intentional backup
                        cli_fix_command=(
                            f"aws rds delete-db-snapshot --region {region} "
                            f"--db-snapshot-identifier {snap_id}"
                        ),
                        fix_destructive=True,
                        evidence={
                            "size_gb": size_gb,
                            "age_days": age_days,
                            "create_time": created.isoformat(),
                            "engine": snap.get("Engine"),
                            "source_db": snap.get("DBInstanceIdentifier"),
                            "encrypted": snap.get("Encrypted"),
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
