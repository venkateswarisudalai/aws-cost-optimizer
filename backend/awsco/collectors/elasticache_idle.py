"""Detect ElastiCache clusters sitting near-idle (CPU ~0) over the last 7 days.

A cache node bills hourly whether or not anything hits it. A node that has
stayed below ~2% CPU for a week is almost certainly an abandoned or oversized
cache that can be deleted or downsized.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import HOURS_PER_MONTH

CHECK_ID = "elasticache.idle"
LOOKBACK_DAYS = 7
CPU_IDLE_THRESHOLD_PCT = 2.0

# Conservative on-demand node hourly prices (USD, us-east-1).
NODE_HOURLY = {
    "cache.t3.micro": 0.017, "cache.t3.small": 0.034, "cache.t3.medium": 0.068,
    "cache.t4g.micro": 0.016, "cache.t4g.small": 0.032, "cache.t4g.medium": 0.064,
    "cache.m5.large": 0.156, "cache.m5.xlarge": 0.311,
    "cache.m6g.large": 0.147, "cache.m6g.xlarge": 0.293,
    "cache.r5.large": 0.216, "cache.r5.xlarge": 0.433,
    "cache.r6g.large": 0.206, "cache.r6g.xlarge": 0.411,
}
DEFAULT_HOURLY = 0.05


def _max_cpu(cw, cluster_id: str) -> float | None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    resp = cw.get_metric_statistics(
        Namespace="AWS/ElastiCache",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "CacheClusterId", "Value": cluster_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Maximum"],
    )
    points = resp.get("Datapoints", [])
    if not points:
        return None
    return max(p["Maximum"] for p in points)


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec = client("elasticache", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        paginator = ec.get_paginator("describe_cache_clusters")
        clusters = [
            c for page in paginator.paginate() for c in page["CacheClusters"]
        ]
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    for c in clusters:
        if c.get("CacheClusterStatus") != "available":
            continue
        cluster_id = c["CacheClusterId"]
        try:
            max_cpu = _max_cpu(cw, cluster_id)
        except ClientError:
            continue
        if max_cpu is None or max_cpu >= CPU_IDLE_THRESHOLD_PCT:
            continue

        node_type = c.get("CacheNodeType", "")
        num_nodes = c.get("NumCacheNodes", 1)
        hourly = NODE_HOURLY.get(node_type, DEFAULT_HOURLY) * num_nodes
        monthly = round(hourly * HOURS_PER_MONTH, 2)
        arn = c.get(
            "ARN",
            f"arn:aws:elasticache:{region}:{account_id}:cluster:{cluster_id}",
        )

        findings.append(
            Finding(
                id=Finding.make_id(CHECK_ID, arn),
                check_id=CHECK_ID,
                title=(
                    f"Idle ElastiCache cluster {cluster_id} "
                    f"({num_nodes}× {node_type})"
                ),
                description=(
                    f"Cluster {cluster_id} peaked at only {max_cpu:.1f}% CPU over the "
                    f"last {LOOKBACK_DAYS} days. If nothing depends on it, delete it; "
                    "otherwise downsize the node type."
                ),
                service="elasticache",
                region=region,
                resource_arn=arn,
                resource_id=cluster_id,
                monthly_savings_usd=monthly,
                severity=Severity.from_monthly_usd(monthly),
                confidence=Confidence.MEDIUM,
                cli_fix_command=(
                    f"aws elasticache delete-cache-cluster --region {region} "
                    f"--cache-cluster-id {cluster_id}"
                ),
                fix_destructive=True,  # in-memory data is lost on delete
                evidence={
                    "node_type": node_type,
                    "num_nodes": num_nodes,
                    "engine": c.get("Engine"),
                    "max_cpu_pct_7d": round(max_cpu, 2),
                },
            )
        )

    return findings
