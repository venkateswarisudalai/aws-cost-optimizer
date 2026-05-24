"""Recommend migrating gp2 volumes to gp3 (20% cheaper, equal or better perf)."""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import gp2_to_gp3_monthly_savings

CHECK_ID = "ebs.gp2-to-gp3"
MIN_SIZE_GB = 10  # ignore tiny volumes; not worth the noise


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    findings: list[Finding] = []

    try:
        paginator = ec2.get_paginator("describe_volumes")
        for page in paginator.paginate(
            Filters=[{"Name": "volume-type", "Values": ["gp2"]}]
        ):
            for vol in page["Volumes"]:
                size_gb = vol["Size"]
                if size_gb < MIN_SIZE_GB:
                    continue
                vol_id = vol["VolumeId"]
                monthly = gp2_to_gp3_monthly_savings(size_gb)
                arn = f"arn:aws:ec2:{region}:{account_id}:volume/{vol_id}"

                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Migrate gp2 → gp3: {vol_id} ({size_gb} GB)",
                        description=(
                            "gp3 is 20% cheaper than gp2 with equal baseline performance "
                            "and configurable IOPS/throughput. Modification is online, "
                            "zero downtime, and reversible."
                        ),
                        service="ec2",
                        region=region,
                        resource_arn=arn,
                        resource_id=vol_id,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.HIGH,
                        cli_fix_command=(
                            f"aws ec2 modify-volume --region {region} "
                            f"--volume-id {vol_id} --volume-type gp3"
                        ),
                        fix_destructive=False,
                        evidence={
                            "size_gb": size_gb,
                            "iops": vol.get("Iops"),
                            "state": vol.get("State"),
                            "attached_to": [
                                a.get("InstanceId") for a in vol.get("Attachments", [])
                            ],
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
