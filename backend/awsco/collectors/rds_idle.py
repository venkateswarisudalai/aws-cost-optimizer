"""Detect RDS DB instances with zero connections over the last 7 days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import HOURS_PER_MONTH

CHECK_ID = "rds.idle"
LOOKBACK_DAYS = 7

# Conservative on-demand hourly prices for common instance classes (USD, us-east-1).
# Underestimating savings is fine.
RDS_HOURLY = {
    "db.t3.micro": 0.017,
    "db.t3.small": 0.034,
    "db.t3.medium": 0.068,
    "db.t4g.micro": 0.016,
    "db.t4g.small": 0.032,
    "db.t4g.medium": 0.065,
    "db.m5.large": 0.171,
    "db.m5.xlarge": 0.342,
    "db.m5.2xlarge": 0.684,
    "db.m6g.large": 0.155,
    "db.r5.large": 0.240,
    "db.r6g.large": 0.226,
}
DEFAULT_HOURLY = 0.05  # fall-back if class unknown


def _max_connections(cw, db_id: str) -> float:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    resp = cw.get_metric_statistics(
        Namespace="AWS/RDS",
        MetricName="DatabaseConnections",
        Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Maximum"],
    )
    points = resp.get("Datapoints", [])
    if not points:
        return 0.0
    return max(p["Maximum"] for p in points)


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    rds = client("rds", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page["DBInstances"]:
                if db.get("DBInstanceStatus") != "available":
                    continue
                db_id = db["DBInstanceIdentifier"]
                try:
                    max_conn = _max_connections(cw, db_id)
                except ClientError:
                    continue
                if max_conn > 0:
                    continue

                instance_class = db.get("DBInstanceClass", "")
                hourly = RDS_HOURLY.get(instance_class, DEFAULT_HOURLY)
                monthly = round(hourly * HOURS_PER_MONTH, 2)
                arn = db.get("DBInstanceArn", f"arn:aws:rds:{region}:{account_id}:db:{db_id}")

                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Idle RDS instance {db_id} ({instance_class})",
                        description=(
                            f"RDS instance {db_id} had zero database connections "
                            f"over the last {LOOKBACK_DAYS} days. Snapshot and delete, "
                            "or stop the instance (RDS stop pauses billing for 7 days)."
                        ),
                        service="rds",
                        region=region,
                        resource_arn=arn,
                        resource_id=db_id,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.MEDIUM,
                        cli_fix_command=(
                            f"aws rds stop-db-instance --region {region} "
                            f"--db-instance-identifier {db_id}"
                        ),
                        fix_destructive=False,
                        evidence={
                            "instance_class": instance_class,
                            "engine": db.get("Engine"),
                            "max_connections_7d": max_conn,
                            "multi_az": db.get("MultiAZ"),
                            "allocated_storage_gb": db.get("AllocatedStorage"),
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
