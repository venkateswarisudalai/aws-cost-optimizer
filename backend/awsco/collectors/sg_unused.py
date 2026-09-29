"""Report security groups that nothing uses (security hygiene, not savings).

Security groups are free, so this saves $0 — it's here because unused groups
are attack surface waiting to be reused: someone attaches an old group with
0.0.0.0/0 rules to a new instance and it's exposed. SOC 2 / CIS reviews flag
them. Findings carry category `hygiene` and never add to savings totals.

"Unused" means: not attached to any network interface, not referenced by
another group's rules, and not a VPC's `default` group (which can't be
deleted). Launch templates can also reference a group without any interface
using it yet — the guidance tells you to check those before deleting.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Confidence, Finding, Severity

CHECK_ID = "sg.unused"

_WORLD = {"0.0.0.0/0", "::/0"}


def _open_to_world(sg: dict) -> list[str]:
    """Inbound rules open to the whole internet, as 'tcp/22' style labels."""
    out = []
    for perm in sg.get("IpPermissions", []):
        cidrs = {r.get("CidrIp") for r in perm.get("IpRanges", [])}
        cidrs |= {r.get("CidrIpv6") for r in perm.get("Ipv6Ranges", [])}
        if cidrs & _WORLD:
            proto = perm.get("IpProtocol", "-1")
            if proto == "-1":
                out.append("all traffic")
            else:
                lo, hi = perm.get("FromPort"), perm.get("ToPort")
                port = str(lo) if lo == hi else f"{lo}-{hi}"
                out.append(f"{proto}/{port}")
    return out


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    findings: list[Finding] = []

    try:
        groups = []
        for page in ec2.get_paginator("describe_security_groups").paginate():
            groups.extend(page.get("SecurityGroups", []))
        if not groups:
            return []

        attached: set[str] = set()
        for page in ec2.get_paginator("describe_network_interfaces").paginate():
            for eni in page.get("NetworkInterfaces", []):
                attached.update(g["GroupId"] for g in eni.get("Groups", []))

        referenced: set[str] = set()
        for sg in groups:
            for perm in sg.get("IpPermissions", []) + sg.get("IpPermissionsEgress", []):
                for pair in perm.get("UserIdGroupPairs", []):
                    if pair.get("GroupId") and pair["GroupId"] != sg["GroupId"]:
                        referenced.add(pair["GroupId"])

        for sg in groups:
            gid = sg["GroupId"]
            if sg.get("GroupName") == "default" or gid in attached or gid in referenced:
                continue
            world = _open_to_world(sg)
            name = sg.get("GroupName", gid)
            arn = f"arn:aws:ec2:{region}:{account_id}:security-group/{gid}"
            findings.append(
                Finding(
                    id=Finding.make_id(CHECK_ID, arn),
                    check_id=CHECK_ID,
                    title=(
                        f"Unused security group '{name}' ({gid})"
                        + (f" — open to the internet on {', '.join(world)}" if world else "")
                    ),
                    description=(
                        "Not attached to any network interface and not referenced by another "
                        "group. It costs nothing, but unused groups get reattached by mistake"
                        + (" — and this one allows inbound traffic from anywhere." if world else ".")
                    ),
                    service="ec2",
                    region=region,
                    resource_arn=arn,
                    resource_id=gid,
                    monthly_savings_usd=0.0,
                    category=Category.HYGIENE,
                    severity=Severity.MEDIUM if world else Severity.LOW,
                    confidence=Confidence.MEDIUM,
                    cli_fix_command=(
                        f"aws ec2 delete-security-group --region {region} --group-id {gid}"
                    ),
                    fix_destructive=False,
                    evidence={
                        "vpc_id": sg.get("VpcId"),
                        "group_name": name,
                        "description": sg.get("Description"),
                        "inbound_rules": len(sg.get("IpPermissions", [])),
                        "outbound_rules": len(sg.get("IpPermissionsEgress", [])),
                        "open_to_world": world,
                        "tags": {t["Key"]: t["Value"] for t in sg.get("Tags", [])},
                    },
                )
            )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
