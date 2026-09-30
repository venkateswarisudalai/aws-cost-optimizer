"""Find io1 volumes that gp3 can serve for less.

io1 bills both storage ($0.125/GB) and every provisioned IOPS ($0.065). gp3
includes 3,000 IOPS free and charges $0.005 per extra IOPS, up to 16,000 IOPS
and 1,000 MB/s. Any io1 volume at or under those limits gets the same IOPS on
gp3 for a fraction of the price — commonly 60–80% cheaper.

We skip volumes above 16,000 IOPS (gp3 can't match them) and io2, whose
durability SLA is a deliberate choice. The migration is online (no detach).
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Confidence, Finding, Severity
from awsco.pricing import GP3_MAX_IOPS, gp3_monthly_cost, io1_monthly_cost

CHECK_ID = "ebs.io1-to-gp3"


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    findings: list[Finding] = []

    try:
        pages = ec2.get_paginator("describe_volumes").paginate(
            Filters=[{"Name": "volume-type", "Values": ["io1"]}]
        )
        for page in pages:
            for vol in page["Volumes"]:
                iops = int(vol.get("Iops") or 0)
                size_gb = int(vol["Size"])
                if iops > GP3_MAX_IOPS:
                    continue
                current = io1_monthly_cost(size_gb, iops)
                target = gp3_monthly_cost(size_gb, iops)
                monthly = round(current - target, 2)
                if monthly < 1:
                    continue

                vol_id = vol["VolumeId"]
                arn = f"arn:aws:ec2:{region}:{account_id}:volume/{vol_id}"
                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Convert io1 volume {vol_id} ({size_gb} GB, {iops} IOPS) to gp3",
                        description=(
                            f"This io1 volume costs ~${current:,.2f}/mo. gp3 delivers the same "
                            f"{iops} IOPS for ~${target:,.2f}/mo. The change is applied online "
                            "with no detach; set --throughput if the workload needs more than "
                            "gp3's 125 MB/s baseline."
                        ),
                        service="ec2",
                        region=region,
                        resource_arn=arn,
                        resource_id=vol_id,
                        monthly_savings_usd=monthly,
                        category=Category.RIGHTSIZING,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.HIGH,
                        cli_fix_command=(
                            f"aws ec2 modify-volume --region {region} --volume-id {vol_id} "
                            f"--volume-type gp3 --iops {max(iops, 3000)}"
                        ),
                        fix_destructive=False,
                        evidence={
                            "size_gb": size_gb,
                            "iops": iops,
                            "current_monthly_usd": current,
                            "gp3_monthly_usd": target,
                            "state": vol.get("State"),
                            "attachments": [a.get("InstanceId") for a in vol.get("Attachments", [])],
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
