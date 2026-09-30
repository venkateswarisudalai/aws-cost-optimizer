"""Where the money actually goes: a Cost Explorer spend baseline.

Findings answer "what can I cut?". This answers the question you need first —
"what am I paying for?" — so savings can be read against real spend (e.g. a
$40/mo finding matters on a $300 bill, not on a $300k one).

Pulls, account-wide:
  - the last 30 full days of unblended cost, grouped by service,
  - month-to-date cost,
  - AWS's forecast for the rest of the current month.

Each Cost Explorer request is billed by AWS at $0.01; a scan makes three.
Returns None (never raises) when Cost Explorer isn't enabled or permitted, so a
missing baseline never fails a scan.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from botocore.exceptions import ClientError

from awsco.aws import client

log = logging.getLogger(__name__)

# Services with less than this share of 30-day spend are folded into "Other".
TOP_SERVICES = 10

# Record types that aren't usage: they'd make spend look negative or lumpy.
_EXCLUDED_RECORD_TYPES = ["Credit", "Refund", "Tax"]


def _amount(block: dict[str, Any]) -> float:
    return float(((block or {}).get("UnblendedCost") or {}).get("Amount", 0.0) or 0.0)


def _exclude_filter() -> dict[str, Any]:
    return {
        "Not": {
            "Dimensions": {"Key": "RECORD_TYPE", "Values": _EXCLUDED_RECORD_TYPES}
        }
    }


def spend_summary(profile: str | None = None, today: date | None = None) -> dict | None:
    today = today or date.today()
    ce = client("ce", "us-east-1", profile)
    start_30 = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()

    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start_30, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            Filter=_exclude_filter(),
        )
    except ClientError as e:
        log.info("Cost Explorer spend unavailable: %s", e.response["Error"]["Code"])
        return None

    # A 30-day window straddles two calendar months, so sum each service across
    # every returned period.
    by_service: dict[str, float] = {}
    for period in resp.get("ResultsByTime", []):
        for group in period.get("Groups", []):
            name = group["Keys"][0]
            by_service[name] = by_service.get(name, 0.0) + _amount(group.get("Metrics", {}))

    total_30d = round(sum(by_service.values()), 2)
    ranked = sorted(by_service.items(), key=lambda kv: -kv[1])
    top = [{"service": s, "cost_usd": round(c, 2)} for s, c in ranked[:TOP_SERVICES] if c >= 0.01]
    other = round(sum(c for _, c in ranked[TOP_SERVICES:]), 2)
    if other >= 0.01:
        top.append({"service": "Other", "cost_usd": other})

    month_start = today.replace(day=1)
    month_to_date = None
    if today > month_start:  # CE rejects an empty (start == end) window
        try:
            mtd = ce.get_cost_and_usage(
                TimePeriod={"Start": month_start.isoformat(), "End": end},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                Filter=_exclude_filter(),
            )
            month_to_date = round(
                sum(_amount(p.get("Total", {})) for p in mtd.get("ResultsByTime", [])), 2
            )
        except ClientError:
            pass

    forecast_month = None
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    try:
        fc = ce.get_cost_forecast(
            TimePeriod={"Start": end, "End": next_month.isoformat()},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
        )
        remaining = float((fc.get("Total") or {}).get("Amount", 0.0) or 0.0)
        forecast_month = round((month_to_date or 0.0) + remaining, 2)
    except ClientError:
        # DataUnavailableException on new accounts, or on the last day of month.
        pass

    return {
        "period_start": start_30,
        "period_end": end,
        "total_30d_usd": total_30d,
        "by_service": top,
        "month_to_date_usd": month_to_date,
        "forecast_month_usd": forecast_month,
        "currency": "USD",
        "source": "cost-explorer",
    }
