"""Reserved Instance purchase recommendations from AWS Cost Explorer.

Everything else in this tool finds money you're wasting. This finds money
you're *leaving on the table*: steady-state on-demand usage that a Reserved
Instance would discount by 30–60%. Cost Explorer already does the math from
your last 30 days of usage — we just surface it next to the waste findings so
the full FinOps picture is in one place.

This is a global, account-wide check (the `ce` endpoint lives in us-east-1), so
the scanner runs it exactly once rather than per region.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Confidence, Finding, Severity

CHECK_ID = "ce.ri-recommendation"
GLOBAL = True  # account-wide; scanner runs this once, not per region

# Services worth checking for RI coverage. (Savings Plans cover compute more
# flexibly — see ce_savings_plans — but RIs still win for RDS/ElastiCache/etc.)
_SERVICES = [
    "Amazon Elastic Compute Cloud - Compute",
    "Amazon Relational Database Service",
    "Amazon ElastiCache",
    "Amazon Redshift",
    "Amazon OpenSearch Service",
]

_SERVICE_SHORT = {
    "Amazon Elastic Compute Cloud - Compute": "EC2",
    "Amazon Relational Database Service": "RDS",
    "Amazon ElastiCache": "ElastiCache",
    "Amazon Redshift": "Redshift",
    "Amazon OpenSearch Service": "OpenSearch",
}

_IGNORABLE = {
    "AccessDeniedException",
    "AccessDenied",
    "DataUnavailableException",
    "OptInRequired",
}


def _recommend_for_service(ce, service: str, account_id: str, region: str) -> list[Finding]:
    try:
        resp = ce.get_reservation_purchase_recommendation(
            Service=service,
            LookbackPeriodInDays="THIRTY_DAYS",
            TermInYears="ONE_YEAR",
            PaymentOption="NO_UPFRONT",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] in _IGNORABLE:
            return []
        raise

    short = _SERVICE_SHORT.get(service, service)
    findings: list[Finding] = []

    for rec in resp.get("Recommendations", []):
        summary = rec.get("RecommendationSummary", {}) or {}
        for i, detail in enumerate(rec.get("RecommendationDetails", [])):
            monthly = round(float(detail.get("EstimatedMonthlySavingsAmount", 0.0) or 0.0), 2)
            if monthly < 1.0:
                continue
            inst = detail.get("InstanceDetails", {}) or {}
            family = next(iter(inst.values()), {}) if inst else {}
            inst_type = family.get("InstanceType") or family.get("NodeType") or "instances"
            count = detail.get("RecommendedNumberOfInstancesToPurchase", "?")
            rec_region = family.get("Region") or "multiple regions"
            synthetic = f"ri:{short}:{inst_type}:{i}"

            findings.append(
                Finding(
                    id=Finding.make_id(CHECK_ID, synthetic),
                    check_id=CHECK_ID,
                    title=(
                        f"Buy {count}× {short} Reserved Instance ({inst_type}) "
                        f"— saves ~${monthly:,.2f}/mo"
                    ),
                    description=(
                        f"Cost Explorer projects ~${monthly:,.2f}/mo in savings from "
                        f"purchasing {count} no-upfront 1-year {short} Reserved "
                        f"Instance(s) of type {inst_type} in {rec_region}, based on your "
                        "last 30 days of on-demand usage. RIs are a financial commitment, "
                        "not a resource change — review utilisation before buying."
                    ),
                    service=short.lower(),
                    region=rec_region,
                    resource_arn=synthetic,
                    resource_id=f"{count}× {inst_type}",
                    monthly_savings_usd=monthly,
                    category=Category.COMMITMENT,
                    severity=Severity.from_monthly_usd(monthly),
                    confidence=Confidence.MEDIUM,
                    cli_fix_command=(
                        "# Review, then purchase in the console: "
                        "https://console.aws.amazon.com/cost-management/home#/ri/recommendations"
                    ),
                    fix_destructive=False,
                    evidence={
                        "service": short,
                        "instance_type": inst_type,
                        "recommended_count": count,
                        "term": "1yr",
                        "payment_option": "NO_UPFRONT",
                        "estimated_monthly_savings_usd": monthly,
                        "estimated_break_even_months": detail.get(
                            "EstimatedBreakEvenInMonths"
                        ),
                        "upfront_cost_usd": detail.get("UpfrontCost"),
                        "summary_total_monthly_savings_usd": summary.get(
                            "TotalEstimatedMonthlySavingsAmount"
                        ),
                        "source": "cost-explorer",
                    },
                )
            )
    return findings


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    # Cost Explorer is only reachable via the us-east-1 endpoint.
    ce = client("ce", "us-east-1", profile)
    findings: list[Finding] = []
    for service in _SERVICES:
        try:
            findings.extend(_recommend_for_service(ce, service, account_id, region))
        except ClientError as e:
            if e.response["Error"]["Code"] in _IGNORABLE:
                continue
            raise
    return findings
