"""Detect NAT gateways with effectively no traffic over the last 7 days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import NAT_GATEWAY_MONTHLY

CHECK_ID = "nat.idle"
LOOKBACK_DAYS = 7
IDLE_BYTES_THRESHOLD = 1_000_000  # 1 MB over 7d == effectively idle


def _total_bytes(cw, nat_id: str) -> float:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    resp = cw.get_metric_statistics(
        Namespace="AWS/NATGateway",
        MetricName="BytesOutToDestination",
        Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
        StartTime=start,
        EndTime=end,
        Period=86400,
        Statistics=["Sum"],
    )
    return sum(p["Sum"] for p in resp.get("Datapoints", []))


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        paginator = ec2.get_paginator("describe_nat_gateways")
        for page in paginator.paginate(
            Filter=[{"Name": "state", "Values": ["available"]}]
        ):
            for ng in page["NatGateways"]:
                nat_id = ng["NatGatewayId"]
                try:
                    bytes_out = _total_bytes(cw, nat_id)
                except ClientError:
                    continue

                if bytes_out > IDLE_BYTES_THRESHOLD:
                    continue

                arn = f"arn:aws:ec2:{region}:{account_id}:natgateway/{nat_id}"
                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Idle NAT gateway {nat_id}",
                        description=(
                            f"This NAT gateway has processed only {int(bytes_out):,} bytes "
                            f"over the last {LOOKBACK_DAYS} days. AWS bills ~$32/mo per "
                            "NAT gateway just for existing. If nothing uses it, delete it."
                        ),
                        service="ec2",
                        region=region,
                        resource_arn=arn,
                        resource_id=nat_id,
                        monthly_savings_usd=round(NAT_GATEWAY_MONTHLY, 2),
                        severity=Severity.from_monthly_usd(NAT_GATEWAY_MONTHLY),
                        confidence=Confidence.HIGH,
                        cli_fix_command=(
                            f"aws ec2 delete-nat-gateway --region {region} "
                            f"--nat-gateway-id {nat_id}"
                        ),
                        fix_destructive=False,  # NAT itself has no data
                        evidence={
                            "bytes_out_7d": int(bytes_out),
                            "vpc_id": ng.get("VpcId"),
                            "subnet_id": ng.get("SubnetId"),
                            "create_time": ng["CreateTime"].isoformat(),
                            "tags": {t["Key"]: t["Value"] for t in ng.get("Tags", [])},
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
