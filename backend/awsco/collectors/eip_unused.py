"""Detect Elastic IPs that are not associated with any resource."""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import PUBLIC_IPV4_MONTHLY

CHECK_ID = "eip.unused"


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    findings: list[Finding] = []

    try:
        resp = ec2.describe_addresses()
        for addr in resp["Addresses"]:
            if addr.get("AssociationId"):
                continue  # attached, skip
            alloc_id = addr.get("AllocationId", addr.get("PublicIp"))
            public_ip = addr.get("PublicIp", "unknown")
            arn = f"arn:aws:ec2:{region}:{account_id}:elastic-ip/{alloc_id}"

            findings.append(
                Finding(
                    id=Finding.make_id(CHECK_ID, arn),
                    check_id=CHECK_ID,
                    title=f"Unused Elastic IP {public_ip}",
                    description=(
                        f"Elastic IP {public_ip} is allocated but not associated. "
                        "Since Feb 2024 AWS bills every public IPv4 at $0.005/hour."
                    ),
                    service="ec2",
                    region=region,
                    resource_arn=arn,
                    resource_id=alloc_id,
                    monthly_savings_usd=round(PUBLIC_IPV4_MONTHLY, 2),
                    severity=Severity.from_monthly_usd(PUBLIC_IPV4_MONTHLY),
                    confidence=Confidence.HIGH,
                    cli_fix_command=(
                        f"aws ec2 release-address --region {region} --allocation-id {alloc_id}"
                    ),
                    fix_destructive=False,
                    evidence={
                        "public_ip": public_ip,
                        "domain": addr.get("Domain"),
                        "tags": {t["Key"]: t["Value"] for t in addr.get("Tags", [])},
                    },
                )
            )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
