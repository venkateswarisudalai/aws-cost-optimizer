"""Detect whole VPCs that look abandoned but still hold billable infrastructure.

A VPC itself is free. What costs money is the infrastructure left inside it
after the workload is gone: NAT gateways, load balancers, interface
endpoints, Transit Gateway attachments and public IPv4 addresses. The
per-resource checks find those one by one; this check says the bigger thing
— "this entire VPC is dead" — and gives one teardown plan.

A VPC is flagged only when ALL of these hold:
  1. It isn't the default VPC.
  2. No workload runs in it: every in-use network interface belongs to
     infrastructure (NAT, load balancer, endpoint, TGW). Any interface owned
     by an instance, Lambda, RDS, ECS task, EKS node, cache, etc. clears it.
  3. It holds billable infrastructure (otherwise it costs nothing to keep).
  4. That infrastructure moved (almost) no traffic in the lookback window.
  5. CloudTrail shows no API activity naming the VPC in the same window
     (best effort — skipped if CloudTrail lookup isn't permitted).

Its savings are the sum of the billable pieces; the matching per-resource
findings (nat.idle, lb.unused, ...) are marked as part of this one in the
scanner so they aren't counted twice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client, lookback_days
from awsco.collectors.vpc_endpoint_idle import _bytes_processed as endpoint_bytes_processed
from awsco.metrics import metric_total
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import (
    LB_MONTHLY,
    NAT_GATEWAY_MONTHLY,
    PUBLIC_IPV4_MONTHLY,
    TGW_ATTACHMENT_MONTHLY,
    VPC_INTERFACE_ENDPOINT_AZ_MONTHLY,
)

CHECK_ID = "vpc.abandoned"

# ENI interface types that are plumbing, not a workload.
_INFRA_INTERFACE_TYPES = {
    "nat_gateway",
    "vpc_endpoint",
    "network_load_balancer",
    "gateway_load_balancer",
    "gateway_load_balancer_endpoint",
    "transit_gateway",
}

TRAFFIC_THRESHOLD_BYTES = 1_000_000


def _is_infra_eni(eni: dict) -> bool:
    if eni.get("InterfaceType") in _INFRA_INTERFACE_TYPES:
        return True
    # ALB / Classic ELB interfaces are plain "interface" type, named "ELB ...".
    return (eni.get("Description") or "").startswith("ELB ")


def _last_cloudtrail_event(region: str, profile: str | None, vpc_id: str, days: int):
    """Most recent CloudTrail event naming this VPC, or None. Returns the
    string "unavailable" if we aren't allowed to look."""
    try:
        ct = client("cloudtrail", region, profile)
        resp = ct.lookup_events(
            LookupAttributes=[{"AttributeKey": "ResourceName", "AttributeValue": vpc_id}],
            StartTime=datetime.now(timezone.utc) - timedelta(days=min(days, 90)),
            MaxResults=1,
        )
        events = resp.get("Events", [])
        return events[0]["EventTime"] if events else None
    except ClientError:
        return "unavailable"


def _lb_traffic(cw, lb: dict, days: int) -> float:
    # arn:...:loadbalancer/app/name/id -> dimension value "app/name/id"
    dim_value = lb["LoadBalancerArn"].split("loadbalancer/", 1)[-1]
    lb_type = lb.get("Type", "application")
    if lb_type == "application":
        ns, metric = "AWS/ApplicationELB", "RequestCount"
    elif lb_type == "network":
        ns, metric = "AWS/NetworkELB", "ProcessedBytes"
    else:
        ns, metric = "AWS/GatewayELB", "ProcessedBytes"
    value, _ = metric_total(cw, ns, metric, [{"Name": "LoadBalancer", "Value": dim_value}], days)
    return value


def _vpc_candidates(ec2, account_id: str) -> list[dict]:
    vpcs = []
    for page in ec2.get_paginator("describe_vpcs").paginate():
        for vpc in page.get("Vpcs", []):
            if vpc.get("IsDefault") or vpc.get("OwnerId", account_id) != account_id:
                continue
            vpcs.append(vpc)
    return vpcs


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    elbv2 = client("elbv2", region, profile)
    cw = client("cloudwatch", region, profile)
    days = lookback_days()
    findings: list[Finding] = []

    try:
        vpcs = _vpc_candidates(ec2, account_id)
        if not vpcs:
            return []

        # Load balancers are listed per region once, then grouped by VPC.
        lbs_by_vpc: dict[str, list[dict]] = {}
        for page in elbv2.get_paginator("describe_load_balancers").paginate():
            for lb in page.get("LoadBalancers", []):
                lbs_by_vpc.setdefault(lb.get("VpcId", ""), []).append(lb)

        for vpc in vpcs:
            vpc_id = vpc["VpcId"]
            vpc_filter = [{"Name": "vpc-id", "Values": [vpc_id]}]

            # 2. Any workload interface means the VPC is in use.
            enis = []
            for page in ec2.get_paginator("describe_network_interfaces").paginate(
                Filters=vpc_filter
            ):
                enis.extend(page.get("NetworkInterfaces", []))
            in_use = [e for e in enis if e.get("Status") == "in-use"]
            if any(not _is_infra_eni(e) for e in in_use):
                continue

            # 3. Inventory the billable pieces.
            members: list[dict] = []
            traffic = 0.0
            serving = False

            nats = ec2.describe_nat_gateways(
                Filters=vpc_filter + [{"Name": "state", "Values": ["available"]}]
            ).get("NatGateways", [])
            for nat in nats:
                members.append({"type": "nat-gateway", "id": nat["NatGatewayId"],
                                "monthly_usd": NAT_GATEWAY_MONTHLY})
                value, _ = metric_total(
                    cw, "AWS/NATGateway", "BytesOutToDestination",
                    [{"Name": "NatGatewayId", "Value": nat["NatGatewayId"]}], days,
                )
                traffic += value

            for lb in lbs_by_vpc.get(vpc_id, []):
                members.append({"type": f"{lb.get('Type', 'application')}-load-balancer",
                                "id": lb["LoadBalancerName"], "arn": lb["LoadBalancerArn"],
                                "monthly_usd": LB_MONTHLY})
                lb_value = _lb_traffic(cw, lb, days)
                if lb.get("Type", "application") == "application" and lb_value > 0:
                    serving = True  # RequestCount: any real request is use
                else:
                    traffic += lb_value

            endpoints = ec2.describe_vpc_endpoints(
                Filters=vpc_filter + [{"Name": "vpc-endpoint-type", "Values": ["Interface"]}]
            ).get("VpcEndpoints", [])
            for ep in endpoints:
                if ep.get("State", "").lower() != "available":
                    continue
                azs = max(1, len(ep.get("SubnetIds", [])))
                members.append({"type": "interface-endpoint", "id": ep["VpcEndpointId"],
                                "service": ep.get("ServiceName"),
                                "monthly_usd": round(VPC_INTERFACE_ENDPOINT_AZ_MONTHLY * azs, 2)})
                traffic += endpoint_bytes_processed(cw, ep["VpcEndpointId"], days)[0]

            tgw_atts = ec2.describe_transit_gateway_vpc_attachments(
                Filters=vpc_filter + [{"Name": "state", "Values": ["available"]}]
            ).get("TransitGatewayVpcAttachments", [])
            for att in tgw_atts:
                members.append({"type": "tgw-attachment", "id": att["TransitGatewayAttachmentId"],
                                "monthly_usd": TGW_ATTACHMENT_MONTHLY})

            public_ips = sorted({
                e["Association"]["PublicIp"] for e in enis if e.get("Association", {}).get("PublicIp")
            })
            for ip in public_ips:
                members.append({"type": "public-ipv4", "id": ip, "monthly_usd": PUBLIC_IPV4_MONTHLY})

            monthly = round(sum(m["monthly_usd"] for m in members), 2)
            if monthly < 1:
                continue  # nothing billable: keeping the VPC costs nothing

            # 4. Any real traffic through its infrastructure means it's in use.
            if serving or traffic > TRAFFIC_THRESHOLD_BYTES:
                continue

            # 5. Recent API activity means someone is working on it.
            last_event = _last_cloudtrail_event(region, profile, vpc_id, days)
            if isinstance(last_event, datetime):
                continue

            peerings = ec2.describe_vpc_peering_connections(
                Filters=[{"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]},
                         {"Name": "status-code", "Values": ["active"]}]
            ).get("VpcPeeringConnections", []) + ec2.describe_vpc_peering_connections(
                Filters=[{"Name": "accepter-vpc-info.vpc-id", "Values": [vpc_id]},
                         {"Name": "status-code", "Values": ["active"]}]
            ).get("VpcPeeringConnections", [])
            flow_logs = ec2.describe_flow_logs(
                Filters=[{"Name": "resource-id", "Values": [vpc_id]}]
            ).get("FlowLogs", [])

            tags = {t["Key"]: t["Value"] for t in vpc.get("Tags", [])}
            name = tags.get("Name", vpc_id)
            confidence = Confidence.LOW if peerings or tgw_atts else Confidence.MEDIUM
            arn = f"arn:aws:ec2:{region}:{account_id}:vpc/{vpc_id}"
            summary = ", ".join(sorted({m["type"] for m in members}))

            findings.append(
                Finding(
                    id=Finding.make_id(CHECK_ID, arn),
                    check_id=CHECK_ID,
                    title=f"VPC '{name}' looks abandoned — ~${monthly:,.2f}/mo in leftover "
                          f"infrastructure",
                    description=(
                        f"No workload runs in {vpc_id} (no instances, Lambda functions, "
                        f"databases or containers), and its {len(members)} billable resources "
                        f"({summary}) moved almost no traffic over {days} days. "
                        + ("CloudTrail shows no activity on it in that time. "
                           if last_event is None else "")
                        + "Tearing it down removes the whole bill for this VPC."
                    ),
                    service="vpc",
                    region=region,
                    resource_arn=arn,
                    resource_id=vpc_id,
                    monthly_savings_usd=monthly,
                    severity=Severity.from_monthly_usd(monthly),
                    confidence=confidence,
                    cli_fix_command=_teardown_script(region, vpc_id, members),
                    fix_destructive=True,
                    evidence={
                        "vpc_name": name,
                        "cidr": vpc.get("CidrBlock"),
                        "members": members,
                        "member_resource_ids": [m["id"] for m in members]
                        + [m["arn"] for m in members if m.get("arn")],
                        "traffic_bytes": int(traffic),
                        "network_interfaces_in_use": len(in_use),
                        "last_cloudtrail_event": None if last_event is None else str(last_event),
                        "active_peering_connections": [
                            p["VpcPeeringConnectionId"] for p in peerings
                        ],
                        "tgw_attachments": [a["TransitGatewayAttachmentId"] for a in tgw_atts],
                        "flow_logs_enabled": bool(flow_logs),
                        "tags": tags,
                    },
                )
            )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings


def _teardown_script(region: str, vpc_id: str, members: list[dict]) -> str:
    """Ordered teardown. Dependencies first: endpoints and load balancers,
    then NAT (whose ENIs block subnet deletion), then the VPC itself."""
    r = f"--region {region}"
    # Run top to bottom, one step at a time (see the finding's guidance).
    lines: list[str] = []
    for m in members:
        if m["type"] == "interface-endpoint":
            lines.append(f"aws ec2 delete-vpc-endpoints {r} --vpc-endpoint-ids {m['id']}")
    for m in members:
        if m["type"].endswith("load-balancer"):
            lines.append(f"aws elbv2 delete-load-balancer {r} --load-balancer-arn {m['arn']}")
    for m in members:
        if m["type"] == "tgw-attachment":
            lines.append(
                f"aws ec2 delete-transit-gateway-vpc-attachment {r} "
                f"--transit-gateway-attachment-id {m['id']}"
            )
    for m in members:
        if m["type"] == "nat-gateway":
            lines.append(f"aws ec2 delete-nat-gateway {r} --nat-gateway-id {m['id']}")
    lines += [
        "# Release the Elastic IPs the NAT gateways used (after they finish deleting):",
        f"aws ec2 describe-addresses {r} --filters Name=domain,Values=vpc",
        "# Then delete subnets, route tables, internet gateway and security groups,",
        f"# and finally: aws ec2 delete-vpc {r} --vpc-id {vpc_id}",
    ]
    return "\n".join(lines)
