"""Detect stopped EC2 instances whose EBS volumes are still being billed.

EC2 compute is free while stopped, but every attached EBS volume continues to
bill. If an instance has been stopped for >30 days, the user is paying for
storage they probably forgot about.
"""

from __future__ import annotations

from datetime import datetime, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import ebs_volume_monthly_cost

CHECK_ID = "ec2.stopped-billed-ebs"
STOPPED_AGE_DAYS_THRESHOLD = 30


def _stopped_for_days(state_transition_reason: str) -> int | None:
    """Best-effort parse of 'User initiated (2024-09-12 14:23:10 GMT)' style strings."""
    import re
    m = re.search(r"\((\d{4}-\d{2}-\d{2})", state_transition_reason or "")
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    findings: list[Finding] = []

    try:
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
        ):
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    days_stopped = _stopped_for_days(
                        inst.get("StateTransitionReason", "")
                    )
                    if days_stopped is None or days_stopped < STOPPED_AGE_DAYS_THRESHOLD:
                        continue

                    inst_id = inst["InstanceId"]
                    monthly = 0.0
                    volume_ids: list[str] = []
                    for bdm in inst.get("BlockDeviceMappings", []):
                        ebs = bdm.get("Ebs") or {}
                        vol_id = ebs.get("VolumeId")
                        if vol_id:
                            volume_ids.append(vol_id)

                    if not volume_ids:
                        continue

                    # Look up actual volume sizes/types
                    try:
                        vols = ec2.describe_volumes(VolumeIds=volume_ids)["Volumes"]
                    except ClientError:
                        continue
                    for v in vols:
                        monthly += ebs_volume_monthly_cost(v["VolumeType"], v["Size"])

                    arn = f"arn:aws:ec2:{region}:{account_id}:instance/{inst_id}"
                    name_tag = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                        inst_id,
                    )

                    findings.append(
                        Finding(
                            id=Finding.make_id(CHECK_ID, arn),
                            check_id=CHECK_ID,
                            title=(
                                f"EC2 '{name_tag}' stopped for {days_stopped}d, "
                                f"still billing ${monthly:.2f}/mo for EBS"
                            ),
                            description=(
                                f"Instance {inst_id} has been stopped for {days_stopped} "
                                "days. Compute is free while stopped, but the attached "
                                f"{len(volume_ids)} EBS volume(s) continue to bill. "
                                "Terminate the instance (snapshots survive) or detach "
                                "and delete the volumes if no longer needed."
                            ),
                            service="ec2",
                            region=region,
                            resource_arn=arn,
                            resource_id=inst_id,
                            monthly_savings_usd=round(monthly, 2),
                            severity=Severity.from_monthly_usd(monthly),
                            confidence=Confidence.HIGH,
                            cli_fix_command=(
                                f"aws ec2 terminate-instances --region {region} "
                                f"--instance-ids {inst_id}"
                            ),
                            fix_destructive=True,
                            evidence={
                                "instance_type": inst.get("InstanceType"),
                                "days_stopped": days_stopped,
                                "volume_ids": volume_ids,
                                "state_transition_reason": inst.get(
                                    "StateTransitionReason"
                                ),
                                "tags": {
                                    t["Key"]: t["Value"] for t in inst.get("Tags", [])
                                },
                            },
                        )
                    )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
