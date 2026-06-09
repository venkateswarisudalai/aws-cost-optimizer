"""Cost anomalies from AWS Cost Anomaly Detection.

A FinOps tool isn't just about steady-state waste — it's about catching the
surprise $4,000 spike *before* the monthly bill lands. AWS Cost Anomaly
Detection runs ML over your spend and flags unexpected jumps by service. We pull
the anomalies from the last 30 days and surface them alongside the savings
findings.

These are one-off impacts, not recurring savings, so `monthly_savings_usd` is 0
and the dollar impact lives in `evidence['impact_usd']`. The dashboard totals
stay honest; anomalies are tracked separately via ScanResult.anomaly_impact_usd.

Requires at least one Cost Anomaly Monitor to be configured on the account; if
none exists the API returns nothing and we emit nothing.

Global, account-wide check (the `ce` endpoint lives in us-east-1).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Confidence, Finding, Severity

CHECK_ID = "ce.anomaly"
GLOBAL = True
LOOKBACK_DAYS = 30
MIN_IMPACT_USD = 5.0  # ignore trivial blips

_IGNORABLE = {
    "AccessDeniedException",
    "AccessDenied",
    "DataUnavailableException",
    "OptInRequired",
}


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ce = client("ce", "us-east-1", profile)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=LOOKBACK_DAYS)
    findings: list[Finding] = []

    try:
        paginator = ce.get_paginator("get_anomalies")
        pages = paginator.paginate(
            DateInterval={
                "StartDate": start.isoformat(),
                "EndDate": end.isoformat(),
            }
        )
        anomalies = []
        for page in pages:
            anomalies.extend(page.get("Anomalies", []))
    except ClientError as e:
        if e.response["Error"]["Code"] in _IGNORABLE:
            return []
        raise

    for a in anomalies:
        impact = a.get("Impact", {}) or {}
        total_impact = round(float(impact.get("TotalImpact", 0.0) or 0.0), 2)
        if total_impact < MIN_IMPACT_USD:
            continue

        anomaly_id = a.get("AnomalyId", "unknown")
        root = a.get("RootCauses", []) or []
        service = next(
            (rc.get("Service") for rc in root if rc.get("Service")),
            a.get("DimensionValue") or "unknown service",
        )
        start_date = a.get("AnomalyStartDate") or ""
        end_date = a.get("AnomalyEndDate") or "ongoing"
        pct = impact.get("TotalImpactPercentage")
        expected = impact.get("TotalExpectedSpend")
        actual = impact.get("TotalActualSpend")
        synthetic = f"anomaly:{anomaly_id}"

        # Severity reflects the size of the spike, even though it isn't a saving.
        sev = Severity.from_monthly_usd(total_impact)

        findings.append(
            Finding(
                id=Finding.make_id(CHECK_ID, synthetic),
                check_id=CHECK_ID,
                title=(
                    f"Cost anomaly: {service} +${total_impact:,.2f} "
                    f"({start_date[:10] or 'recent'})"
                ),
                description=(
                    f"AWS Cost Anomaly Detection flagged unexpected {service} spend of "
                    f"~${total_impact:,.2f} above the forecast"
                    + (f" (+{pct:.0f}%)" if isinstance(pct, (int, float)) else "")
                    + f" starting {start_date[:10] or 'recently'}. Investigate the root "
                    "cause — a runaway job, a new deploy, or a forgotten resource. This is "
                    "a one-off impact, not a recurring saving."
                ),
                service=str(service).lower().split()[0] if service else "billing",
                region="global",
                resource_arn=synthetic,
                resource_id=anomaly_id,
                monthly_savings_usd=0.0,  # one-off impact, not a recurring saving
                category=Category.ANOMALY,
                severity=sev,
                confidence=Confidence.HIGH,
                cli_fix_command=(
                    "# Investigate in the console: "
                    "https://console.aws.amazon.com/cost-management/home#/anomaly-detection/monitors"
                ),
                fix_destructive=False,
                evidence={
                    "impact_usd": total_impact,
                    "impact_percentage": pct,
                    "expected_spend_usd": expected,
                    "actual_spend_usd": actual,
                    "anomaly_start": start_date,
                    "anomaly_end": end_date,
                    "root_cause_service": service,
                    "root_causes": root[:5],
                    "source": "cost-anomaly-detection",
                },
            )
        )

    return findings
