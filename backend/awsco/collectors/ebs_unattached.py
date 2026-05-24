"""Detect EBS volumes in 'available' state (i.e., not attached to anything)."""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import ebs_volume_monthly_cost

CHECK_ID = "ebs.unattached"


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    findings: list[Finding] = []

    try:
        paginator = ec2.get_paginator("describe_volumes")
        pages = paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}])
        for page in pages:
            for vol in page["Volumes"]:
                vol_id = vol["VolumeId"]
                size_gb = vol["Size"]
                vol_type = vol["VolumeType"]
                monthly = ebs_volume_monthly_cost(vol_type, size_gb)
                arn = f"arn:aws:ec2:{region}:{account_id}:volume/{vol_id}"

                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Unattached EBS volume {vol_id} ({size_gb} GB, {vol_type})",
                        description=(
                            f"This {size_gb} GB {vol_type} volume is in 'available' state "
                            "(not attached to any instance) but still billed."
                        ),
                        service="ec2",
                        region=region,
                        resource_arn=arn,
                        resource_id=vol_id,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.HIGH,
                        cli_fix_command=(
                            f"aws ec2 delete-volume --region {region} --volume-id {vol_id}"
                        ),
                        fix_destructive=True,
                        evidence={
                            "size_gb": size_gb,
                            "volume_type": vol_type,
                            "create_time": vol["CreateTime"].isoformat(),
                            "availability_zone": vol["AvailabilityZone"],
                            "tags": {t["Key"]: t["Value"] for t in vol.get("Tags", [])},
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
