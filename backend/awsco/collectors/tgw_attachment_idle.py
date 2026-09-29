"""Detect Transit Gateway attachments that carried no traffic.

Every attachment (VPC, VPN, peering, Connect) bills ~$0.05/hour — about
$36/mo — to the account that owns the attached resource, whether or not a
byte crosses it. Attachments to decommissioned VPCs are a common leftover.

CloudWatch publishes per-attachment traffic in the Transit Gateway owner's
account, so we only judge attachments where this account owns both the
gateway and the attached resource; anything else we can't see into is skipped.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client, lookback_days
from awsco.metrics import metric_total
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import TGW_ATTACHMENT_MONTHLY

CHECK_ID = "tgw.attachment-idle"


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    cw = client("cloudwatch", region, profile)
    days = lookback_days()
    findings: list[Finding] = []

    try:
        pages = ec2.get_paginator("describe_transit_gateway_attachments").paginate(
            Filters=[{"Name": "state", "Values": ["available"]}]
        )
        for page in pages:
            for att in page.get("TransitGatewayAttachments", []):
                if att.get("ResourceOwnerId") != account_id:
                    continue  # billed to someone else
                if att.get("TransitGatewayOwnerId") != account_id:
                    continue  # metrics live in the TGW owner's account
                att_id = att["TransitGatewayAttachmentId"]
                tgw_id = att["TransitGatewayId"]
                dims = [
                    {"Name": "TransitGateway", "Value": tgw_id},
                    {"Name": "TransitGatewayAttachment", "Value": att_id},
                ]
                bytes_in, has_in = metric_total(cw, "AWS/TransitGateway", "BytesIn", dims, days)
                bytes_out, has_out = metric_total(cw, "AWS/TransitGateway", "BytesOut", dims, days)
                traffic = bytes_in + bytes_out
                if traffic > 1_000_000:
                    continue

                monthly = TGW_ATTACHMENT_MONTHLY
                kind = att.get("ResourceType", "vpc")
                target = att.get("ResourceId", "")
                arn = f"arn:aws:ec2:{region}:{account_id}:transit-gateway-attachment/{att_id}"
                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Idle Transit Gateway attachment {att_id} ({kind} {target})",
                        description=(
                            f"This {kind} attachment to {tgw_id} carried "
                            f"{'no traffic' if not traffic else f'{traffic / 1e6:.2f} MB'} over "
                            f"{days} days and still bills ~${monthly:.2f}/mo."
                        ),
                        service="vpc",
                        region=region,
                        resource_arn=arn,
                        resource_id=att_id,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.MEDIUM if (has_in or has_out) else Confidence.LOW,
                        cli_fix_command=(
                            f"aws ec2 delete-transit-gateway-vpc-attachment --region {region} "
                            f"--transit-gateway-attachment-id {att_id}"
                            if kind == "vpc"
                            else f"# Delete the {kind} attachment {att_id} in the VPC console"
                        ),
                        fix_destructive=False,
                        evidence={
                            "transit_gateway_id": tgw_id,
                            "resource_type": kind,
                            "resource_id": target,
                            "bytes": int(traffic),
                            "metrics_found": has_in or has_out,
                            "created": str(att.get("CreationTime", "")),
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
