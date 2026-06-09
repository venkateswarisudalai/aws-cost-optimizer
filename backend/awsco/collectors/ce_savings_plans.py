"""Savings Plans purchase recommendations from AWS Cost Explorer.

Savings Plans are the more flexible cousin of Reserved Instances: you commit to
a steady hourly spend ($/hr) and AWS discounts compute (EC2, Fargate, Lambda)
automatically, even as you change instance families or regions. Cost Explorer
recommends an hourly commitment from your recent usage and estimates the
monthly saving — we surface its top recommendation per plan type.

Global, account-wide check (the `ce` endpoint lives in us-east-1); the scanner
runs it once rather than per region.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Confidence, Finding, Severity

CHECK_ID = "ce.savings-plan"
GLOBAL = True

# (SavingsPlansType, human label). COMPUTE_SP is the most flexible; EC2_INSTANCE_SP
# is cheaper but locks you to a family/region.
_PLAN_TYPES = [
    ("COMPUTE_SP", "Compute Savings Plan"),
    ("EC2_INSTANCE_SP", "EC2 Instance Savings Plan"),
]

_IGNORABLE = {
    "AccessDeniedException",
    "AccessDenied",
    "DataUnavailableException",
    "OptInRequired",
}


def _recommend(ce, plan_type: str, label: str) -> list[Finding]:
    try:
        resp = ce.get_savings_plans_purchase_recommendation(
            SavingsPlansType=plan_type,
            TermInYears="ONE_YEAR",
            PaymentOption="NO_UPFRONT",
            LookbackPeriodInDays="THIRTY_DAYS",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] in _IGNORABLE:
            return []
        raise

    rec = resp.get("SavingsPlansPurchaseRecommendation", {}) or {}
    summary = rec.get("SavingsPlansPurchaseRecommendationSummary", {}) or {}
    monthly = round(float(summary.get("EstimatedMonthlySavingsAmount", 0.0) or 0.0), 2)
    if monthly < 1.0:
        return []

    hourly_commitment = summary.get("HourlyCommitmentToPurchase")
    pct = summary.get("EstimatedSavingsPercentage")
    synthetic = f"sp:{plan_type}"

    return [
        Finding(
            id=Finding.make_id(CHECK_ID, synthetic),
            check_id=CHECK_ID,
            title=(
                f"Buy a {label} (~${hourly_commitment}/hr commit) "
                f"— saves ~${monthly:,.2f}/mo"
            ),
            description=(
                f"Cost Explorer projects ~${monthly:,.2f}/mo (~{pct}%) in savings from a "
                f"1-year no-upfront {label} committing ~${hourly_commitment}/hour, based "
                "on your last 30 days of compute usage. Savings Plans apply automatically "
                "across instance families — but they're a financial commitment, so confirm "
                "your baseline usage is stable before purchasing."
            ),
            service="compute",
            region="global",
            resource_arn=synthetic,
            resource_id=label,
            monthly_savings_usd=monthly,
            category=Category.COMMITMENT,
            severity=Severity.from_monthly_usd(monthly),
            confidence=Confidence.MEDIUM,
            cli_fix_command=(
                "# Review, then purchase in the console: "
                "https://console.aws.amazon.com/cost-management/home#/savings-plans/recommendations"
            ),
            fix_destructive=False,
            evidence={
                "plan_type": plan_type,
                "hourly_commitment_usd": hourly_commitment,
                "estimated_savings_percentage": pct,
                "term": "1yr",
                "payment_option": "NO_UPFRONT",
                "estimated_monthly_savings_usd": monthly,
                "estimated_roi": summary.get("EstimatedROI"),
                "current_on_demand_spend_usd": summary.get("CurrentOnDemandSpend"),
                "source": "cost-explorer",
            },
        )
    ]


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ce = client("ce", "us-east-1", profile)
    findings: list[Finding] = []
    for plan_type, label in _PLAN_TYPES:
        try:
            findings.extend(_recommend(ce, plan_type, label))
        except ClientError as e:
            if e.response["Error"]["Code"] in _IGNORABLE:
                continue
            raise
    return findings
