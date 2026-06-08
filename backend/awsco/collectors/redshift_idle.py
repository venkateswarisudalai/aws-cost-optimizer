"""Detect Redshift clusters with zero database connections over the last 7 days.

Redshift is one of the most expensive things you can leave running — even a
small two-node cluster is hundreds of dollars a month. A cluster with no
connections for a week is a prime candidate to pause (billing stops) or delete
with a final snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import HOURS_PER_MONTH

CHECK_ID = "redshift.idle"
LOOKBACK_DAYS = 7

# Conservative on-demand node hourly prices (USD, us-east-1).
NODE_HOURLY = {
    "dc2.large": 0.25, "dc2.8xlarge": 4.80,
    "ds2.xlarge": 0.85, "ds2.8xlarge": 6.80,
    "ra3.xlplus": 1.086, "ra3.4xlarge": 3.26, "ra3.16xlarge": 13.04,
}
DEFAULT_HOURLY = 0.25


def _max_connections(cw, cluster_id: str) -> float | None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    resp = cw.get_metric_statistics(
        Namespace="AWS/Redshift",
        MetricName="DatabaseConnections",
        Dimensions=[{"Name": "ClusterIdentifier", "Value": cluster_id}],
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
    rs = client("redshift", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        paginator = rs.get_paginator("describe_clusters")
        clusters = [c for page in paginator.paginate() for c in page["Clusters"]]
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    for c in clusters:
        if c.get("ClusterStatus") != "available":
            continue
        cluster_id = c["ClusterIdentifier"]
        try:
            max_conn = _max_connections(cw, cluster_id)
        except ClientError:
            continue
        # No datapoints means CloudWatch has no record — treat as idle only when
        # the metric explicitly reports zero connections.
        if max_conn is None or max_conn > 0:
            continue

        node_type = c.get("NodeType", "")
        num_nodes = c.get("NumberOfNodes", 1)
        hourly = NODE_HOURLY.get(node_type, DEFAULT_HOURLY) * num_nodes
        monthly = round(hourly * HOURS_PER_MONTH, 2)
        arn = f"arn:aws:redshift:{region}:{account_id}:cluster:{cluster_id}"

        findings.append(
            Finding(
                id=Finding.make_id(CHECK_ID, arn),
                check_id=CHECK_ID,
                title=(
                    f"Idle Redshift cluster {cluster_id} "
                    f"({num_nodes}× {node_type})"
                ),
                description=(
                    f"Cluster {cluster_id} had zero database connections over the last "
                    f"{LOOKBACK_DAYS} days. Pause it (billing stops while paused) or "
                    "delete it with a final snapshot."
                ),
                service="redshift",
                region=region,
                resource_arn=arn,
                resource_id=cluster_id,
                monthly_savings_usd=monthly,
                severity=Severity.from_monthly_usd(monthly),
                confidence=Confidence.MEDIUM,
                cli_fix_command=(
                    f"aws redshift pause-cluster --region {region} "
                    f"--cluster-identifier {cluster_id}"
                ),
                fix_destructive=False,  # pause is reversible
                evidence={
                    "node_type": node_type,
                    "number_of_nodes": num_nodes,
                    "max_connections_7d": max_conn,
                    "db_name": c.get("DBName"),
                },
            )
        )

    return findings
