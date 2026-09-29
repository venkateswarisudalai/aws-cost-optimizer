"""Detect Site-to-Site VPN connections that carried no traffic.

A VPN connection bills ~$0.05/hour (~$36/mo) while it exists, even with both
tunnels down. Connections to a closed office or a migrated data centre are a
classic forgotten charge.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client, lookback_days
from awsco.metrics import metric_total
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import VPN_CONNECTION_MONTHLY

CHECK_ID = "vpn.idle"


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    cw = client("cloudwatch", region, profile)
    days = lookback_days()
    findings: list[Finding] = []

    try:
        resp = ec2.describe_vpn_connections(
            Filters=[{"Name": "state", "Values": ["available"]}]
        )
        for vpn in resp.get("VpnConnections", []):
            vpn_id = vpn["VpnConnectionId"]
            dims = [{"Name": "VpnId", "Value": vpn_id}]
            data_in, has_in = metric_total(cw, "AWS/VPN", "TunnelDataIn", dims, days)
            data_out, has_out = metric_total(cw, "AWS/VPN", "TunnelDataOut", dims, days)
            traffic = data_in + data_out
            if traffic > 1_000_000:
                continue

            tunnels = [t.get("Status") for t in vpn.get("VgwTelemetry", [])]
            monthly = VPN_CONNECTION_MONTHLY
            arn = f"arn:aws:ec2:{region}:{account_id}:vpn-connection/{vpn_id}"
            findings.append(
                Finding(
                    id=Finding.make_id(CHECK_ID, arn),
                    check_id=CHECK_ID,
                    title=f"Idle Site-to-Site VPN {vpn_id} (tunnels: {', '.join(tunnels) or '?'})",
                    description=(
                        f"This VPN connection moved "
                        f"{'no data' if not traffic else f'{traffic / 1e6:.2f} MB'} over {days} "
                        f"days and still bills ~${monthly:.2f}/mo."
                    ),
                    service="vpc",
                    region=region,
                    resource_arn=arn,
                    resource_id=vpn_id,
                    monthly_savings_usd=monthly,
                    severity=Severity.from_monthly_usd(monthly),
                    confidence=Confidence.MEDIUM if (has_in or has_out) else Confidence.LOW,
                    cli_fix_command=(
                        f"aws ec2 delete-vpn-connection --region {region} "
                        f"--vpn-connection-id {vpn_id}"
                    ),
                    fix_destructive=False,
                    evidence={
                        "customer_gateway_id": vpn.get("CustomerGatewayId"),
                        "vpn_gateway_id": vpn.get("VpnGatewayId"),
                        "transit_gateway_id": vpn.get("TransitGatewayId"),
                        "tunnel_status": tunnels,
                        "bytes": int(traffic),
                        "metrics_found": has_in or has_out,
                    },
                )
            )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
