"""Detect CloudWatch Logs groups with no retention policy (i.e., 'Never expire').

These groups grow forever — a classic silent cost leak.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import CLOUDWATCH_LOGS_STORAGE_GB_MONTH

CHECK_ID = "logs.no-retention"


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    logs = client("logs", region, profile)
    findings: list[Finding] = []

    try:
        paginator = logs.get_paginator("describe_log_groups")
        for page in paginator.paginate():
            for lg in page["logGroups"]:
                if lg.get("retentionInDays"):
                    continue  # has a policy, skip
                name = lg["logGroupName"]
                stored_bytes = lg.get("storedBytes", 0)
                stored_gb = stored_bytes / (1024 ** 3)
                monthly_current = round(
                    stored_gb * CLOUDWATCH_LOGS_STORAGE_GB_MONTH, 2
                )
                arn = lg.get(
                    "arn",
                    f"arn:aws:logs:{region}:{account_id}:log-group:{name}",
                )

                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Log group '{name}' has no retention policy",
                        description=(
                            "This log group grows indefinitely. Setting retention "
                            "(e.g., 30 days) caps storage cost and is one of the highest-"
                            "ROI changes you can make. Current storage cost shown is "
                            "what you're already paying — savings grow over time."
                        ),
                        service="logs",
                        region=region,
                        resource_arn=arn,
                        resource_id=name,
                        monthly_savings_usd=monthly_current,
                        severity=Severity.from_monthly_usd(monthly_current),
                        confidence=Confidence.HIGH,
                        cli_fix_command=(
                            f"aws logs put-retention-policy --region {region} "
                            f"--log-group-name '{name}' --retention-in-days 30"
                        ),
                        fix_destructive=False,
                        evidence={
                            "stored_bytes": stored_bytes,
                            "stored_gb": round(stored_gb, 3),
                            "created_at_ms": lg.get("creationTime"),
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
