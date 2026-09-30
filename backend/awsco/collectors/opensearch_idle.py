"""Detect OpenSearch / Elasticsearch domains with no real traffic for 7 days.

An OpenSearch domain bills for every data + master node, hourly, whether or not
anything queries it. A domain that has served ~zero searches and ~zero indexing
for a week is almost always an abandoned proof-of-concept or a replaced cluster
nobody deleted — and even a modest 2-node domain runs well over $100/mo.

We require BOTH search and indexing to be effectively idle before flagging, so a
write-only ingest domain or a read-only archive isn't mislabelled. CloudWatch's
`AWS/ES` namespace (still the name for OpenSearch metrics) is keyed by the domain
name plus the account id.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client, lookback_days
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import HOURS_PER_MONTH

CHECK_ID = "opensearch.idle"
# Total search + indexing operations below this over the window == idle.
ACTIVITY_THRESHOLD = 1.0

# Conservative on-demand node hourly prices (USD, us-east-1, ".search" suffix
# dropped for matching). Underestimating savings is fine.
NODE_HOURLY = {
    "t3.small.search": 0.036, "t3.medium.search": 0.073,
    "t2.small.search": 0.036, "t2.medium.search": 0.073,
    "m5.large.search": 0.142, "m5.xlarge.search": 0.283,
    "m6g.large.search": 0.128, "m6g.xlarge.search": 0.256,
    "c5.large.search": 0.121, "c5.xlarge.search": 0.242,
    "r5.large.search": 0.186, "r5.xlarge.search": 0.372,
    "r6g.large.search": 0.167, "r6g.xlarge.search": 0.335,
}
DEFAULT_HOURLY = 0.10


def _sum_metric(cw, domain: str, account_id: str, metric: str) -> float:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days())
    resp = cw.get_metric_statistics(
        Namespace="AWS/ES",
        MetricName=metric,
        Dimensions=[
            {"Name": "DomainName", "Value": domain},
            {"Name": "ClientId", "Value": account_id},
        ],
        StartTime=start,
        EndTime=end,
        Period=86400,
        Statistics=["Sum"],
    )
    return sum(p["Sum"] for p in resp.get("Datapoints", []))


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    os_client = client("opensearch", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        names = [
            d["DomainName"]
            for d in os_client.list_domain_names().get("DomainNames", [])
        ]
    except ClientError as e:
        if e.response["Error"]["Code"] in {
            "AccessDenied",
            "AccessDeniedException",
            "UnauthorizedOperation",
            "ResourceNotFoundException",
        }:
            return []
        raise

    for name in names:
        try:
            domain = os_client.describe_domain(DomainName=name)["DomainStatus"]
        except ClientError:
            continue

        # Only score domains that are fully up; ones still being created/deleted
        # legitimately show no traffic.
        if domain.get("Processing") or not domain.get("Created") or domain.get("Deleted"):
            continue

        try:
            activity = _sum_metric(
                cw, name, account_id, "SearchRate"
            ) + _sum_metric(cw, name, account_id, "IndexingRate")
        except ClientError:
            continue
        if activity > ACTIVITY_THRESHOLD:
            continue

        cluster = domain.get("ClusterConfig", {}) or {}
        inst_type = cluster.get("InstanceType", "")
        inst_count = cluster.get("InstanceCount", 1) or 1
        hourly = NODE_HOURLY.get(inst_type, DEFAULT_HOURLY) * inst_count

        # Dedicated master nodes bill too — fold them in when present.
        if cluster.get("DedicatedMasterEnabled"):
            m_type = cluster.get("DedicatedMasterType", "")
            m_count = cluster.get("DedicatedMasterCount", 0) or 0
            hourly += NODE_HOURLY.get(m_type, DEFAULT_HOURLY) * m_count

        monthly = round(hourly * HOURS_PER_MONTH, 2)
        arn = domain.get(
            "ARN", f"arn:aws:es:{region}:{account_id}:domain/{name}"
        )

        findings.append(
            Finding(
                id=Finding.make_id(CHECK_ID, arn),
                check_id=CHECK_ID,
                title=(
                    f"Idle OpenSearch domain '{name}' "
                    f"({inst_count}× {inst_type or 'unknown'})"
                ),
                description=(
                    f"Domain '{name}' served effectively no searches or indexing over the "
                    f"last {lookback_days()} days. If nothing depends on it, delete it (take a "
                    "manual snapshot first); otherwise downsize the node type or count."
                ),
                service="es",
                region=region,
                resource_arn=arn,
                resource_id=name,
                monthly_savings_usd=monthly,
                severity=Severity.from_monthly_usd(monthly),
                confidence=Confidence.MEDIUM,
                cli_fix_command=(
                    f"aws opensearch delete-domain --region {region} --domain-name {name}"
                ),
                fix_destructive=True,  # deleting a domain drops its indices
                evidence={
                    "instance_type": inst_type,
                    "instance_count": inst_count,
                    "dedicated_master": cluster.get("DedicatedMasterEnabled", False),
                    "engine_version": domain.get("EngineVersion"),
                    "search_plus_indexing_7d": round(activity, 2),
                },
            )
        )

    return findings
