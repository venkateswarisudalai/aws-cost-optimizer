"""Small CloudWatch helpers shared by the network checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def metric_total(
    cw,
    namespace: str,
    metric: str,
    dimensions: list[dict[str, str]],
    days: int,
    stat: str = "Sum",
) -> tuple[float, bool]:
    """Sum (or max) of a metric over the last `days` days, at daily resolution.

    Returns (value, has_data). `has_data` is False when CloudWatch returned no
    datapoints at all, which for traffic metrics usually means no traffic, but
    callers should treat it as weaker evidence than an explicit zero.
    """
    end = datetime.now(timezone.utc)
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric,
        Dimensions=dimensions,
        StartTime=end - timedelta(days=days),
        EndTime=end,
        Period=86400,
        Statistics=[stat],
    )
    points = resp.get("Datapoints", [])
    if not points:
        return 0.0, False
    values = [float(p.get(stat, 0.0)) for p in points]
    return (max(values) if stat == "Maximum" else sum(values)), True


def matching_metrics(cw, namespace: str, metric: str, dimension: str, value: str) -> list[list]:
    """Every dimension set CloudWatch has for metric where `dimension == value`.

    Needed when a metric is published with extra dimensions we can't know up
    front (e.g. PrivateLink endpoints also carry 'Service Name')."""
    out: list[list] = []
    for page in cw.get_paginator("list_metrics").paginate(
        Namespace=namespace,
        MetricName=metric,
        Dimensions=[{"Name": dimension, "Value": value}],
    ):
        out.extend(m["Dimensions"] for m in page.get("Metrics", []))
    return out
