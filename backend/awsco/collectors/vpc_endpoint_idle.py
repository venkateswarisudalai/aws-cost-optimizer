"""Detect interface VPC endpoints that processed no traffic.

Interface endpoints (PrivateLink) bill ~$0.01/hour *per Availability Zone*
they're deployed in — about $7.20/mo per AZ, so a 3-AZ endpoint is ~$21.60/mo
before any data is sent. They pile up: teams add one per AWS service (ECR,
STS, SSM, Logs...) per VPC and never remove them.

Gateway endpoints (S3, DynamoDB) are free and are never flagged.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client, lookback_days
from awsco.metrics import matching_metrics, metric_total
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import VPC_INTERFACE_ENDPOINT_AZ_MONTHLY

CHECK_ID = "vpc.endpoint-idle"
NAMESPACE = "AWS/PrivateLinkEndpoints"


def _bytes_processed(cw, endpoint_id: str, days: int) -> tuple[float, bool]:
    total, any_data = 0.0, False
    for dims in matching_metrics(cw, NAMESPACE, "BytesProcessed", "VPC Endpoint Id", endpoint_id):
        # Per-subnet series repeat the endpoint-level total; count each byte once.
        if any(d["Name"] == "Subnet Id" for d in dims):
            continue
        value, has = metric_total(cw, NAMESPACE, "BytesProcessed", dims, days)
        total += value
        any_data = any_data or has
    return total, any_data


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    cw = client("cloudwatch", region, profile)
    days = lookback_days()
    findings: list[Finding] = []

    try:
        pages = ec2.get_paginator("describe_vpc_endpoints").paginate(
            Filters=[{"Name": "vpc-endpoint-type", "Values": ["Interface"]}]
        )
        for page in pages:
            for ep in page.get("VpcEndpoints", []):
                if ep.get("State", "").lower() != "available" or ep.get("RequesterManaged"):
                    continue  # AWS-managed endpoints (e.g. for a service you use) aren't yours to delete
                ep_id = ep["VpcEndpointId"]
                azs = max(1, len(ep.get("SubnetIds", [])))
                processed, has_data = _bytes_processed(cw, ep_id, days)
                if processed > 1_000_000:  # >1 MB in the window = in use
                    continue

                monthly = round(VPC_INTERFACE_ENDPOINT_AZ_MONTHLY * azs, 2)
                service = ep.get("ServiceName", "")
                short = service.split(".")[-1] if service else "endpoint"
                arn = f"arn:aws:ec2:{region}:{account_id}:vpc-endpoint/{ep_id}"
                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Idle interface endpoint {ep_id} ({short}, {azs} AZ)",
                        description=(
                            f"This PrivateLink endpoint for {service} processed "
                            f"{'no' if not processed else f'only {processed / 1e6:.2f} MB of'} "
                            f"traffic over {days} days but bills ~${monthly:.2f}/mo "
                            f"(${VPC_INTERFACE_ENDPOINT_AZ_MONTHLY:.2f} per AZ)."
                        ),
                        service="vpc",
                        region=region,
                        resource_arn=arn,
                        resource_id=ep_id,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.MEDIUM if has_data else Confidence.LOW,
                        cli_fix_command=(
                            f"aws ec2 delete-vpc-endpoints --region {region} "
                            f"--vpc-endpoint-ids {ep_id}"
                        ),
                        fix_destructive=False,
                        evidence={
                            "vpc_id": ep.get("VpcId"),
                            "service_name": service,
                            "availability_zones": azs,
                            "bytes_processed": int(processed),
                            "metrics_found": has_data,
                            "private_dns_enabled": ep.get("PrivateDnsEnabled"),
                            "created": str(ep.get("CreationTimestamp", "")),
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
