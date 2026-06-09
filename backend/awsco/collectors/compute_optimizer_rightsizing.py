"""Rightsizing recommendations from AWS Compute Optimizer.

The idle-EC2 collector catches instances that are *almost completely* unused.
This one catches the larger, quieter problem: instances that are genuinely in
use but provisioned two or three sizes too big. AWS Compute Optimizer watches
real CPU / memory / network utilisation and recommends a cheaper instance type
that still fits the workload, with a dollar figure attached.

We only surface OVER_PROVISIONED instances (where downsizing saves money) and
take Compute Optimizer's own monthly-savings estimate for the best-ranked
option. Compute Optimizer must be enrolled on the account; if it isn't, the API
returns OptInRequired and we simply emit nothing.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Confidence, Finding, Severity

CHECK_ID = "ec2.rightsizing"

# Compute Optimizer error codes that just mean "nothing to report here".
_IGNORABLE = {
    "AccessDeniedException",
    "AccessDenied",
    "OptInRequiredException",
    "OptInRequired",
    "ResourceNotFoundException",
}


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    co = client("compute-optimizer", region, profile)
    findings: list[Finding] = []

    try:
        paginator = co.get_paginator("get_ec2_instance_recommendations")
        for page in paginator.paginate():
            for rec in page.get("instanceRecommendations", []):
                if rec.get("finding") != "OVER_PROVISIONED":
                    continue

                options = rec.get("recommendationOptions", [])
                # Best-ranked option with a real, positive saving.
                best = None
                best_savings = 0.0
                for opt in options:
                    so = opt.get("savingsOpportunity", {}) or {}
                    val = float((so.get("estimatedMonthlySavings", {}) or {}).get("value", 0.0))
                    if val > best_savings:
                        best, best_savings = opt, val
                if best is None or best_savings <= 0:
                    continue

                arn = rec.get("instanceArn", "")
                inst_id = arn.split("/")[-1] if arn else rec.get("instanceName", "unknown")
                name = rec.get("instanceName") or inst_id
                current_type = rec.get("currentInstanceType", "?")
                target_type = best.get("instanceType", "?")
                monthly = round(best_savings, 2)
                perf_risk = best.get("performanceRisk")

                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn or inst_id),
                        check_id=CHECK_ID,
                        title=(
                            f"Rightsize EC2 '{name}': {current_type} → {target_type} "
                            f"(saves ~${monthly:,.2f}/mo)"
                        ),
                        description=(
                            f"Compute Optimizer flags {inst_id} ({current_type}) as "
                            f"over-provisioned based on real utilisation. Moving to "
                            f"{target_type} keeps the workload covered while cutting the "
                            "bill. Resizing needs a brief stop/start (EBS data is kept). "
                            "Validate the target type against your peak load first."
                        ),
                        service="ec2",
                        region=region,
                        resource_arn=arn or f"arn:aws:ec2:{region}:{account_id}:instance/{inst_id}",
                        resource_id=inst_id,
                        monthly_savings_usd=monthly,
                        category=Category.RIGHTSIZING,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.MEDIUM,
                        cli_fix_command=(
                            f"aws ec2 stop-instances --region {region} --instance-ids {inst_id} && "
                            f"aws ec2 modify-instance-attribute --region {region} "
                            f"--instance-id {inst_id} --instance-type {target_type} && "
                            f"aws ec2 start-instances --region {region} --instance-ids {inst_id}"
                        ),
                        fix_destructive=False,  # resize preserves EBS data
                        evidence={
                            "current_instance_type": current_type,
                            "recommended_instance_type": target_type,
                            "finding": rec.get("finding"),
                            "performance_risk": perf_risk,
                            "lookback_period_days": rec.get("lookBackPeriodInDays"),
                            "estimated_monthly_savings_usd": monthly,
                            "source": "compute-optimizer",
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in _IGNORABLE:
            return []
        raise

    return findings
