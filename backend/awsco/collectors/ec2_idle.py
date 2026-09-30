"""Detect running EC2 instances with near-zero CPU over the last 7 days.

Compute is the single biggest line item on most bills. An instance that is
*running* (so fully billed) but has sat below a few percent CPU for a week is
either forgotten or massively over-provisioned. We surface the full instance
cost as the savings ceiling — stop it, or rightsize it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client, lookback_days
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import HOURS_PER_MONTH

CHECK_ID = "ec2.idle"
CPU_IDLE_THRESHOLD_PCT = 5.0  # max CPU below this over 7d == idle

# Conservative on-demand hourly prices for common instance types (USD, us-east-1).
# Underestimating savings is fine; overestimating is not.
EC2_HOURLY = {
    "t2.micro": 0.0116, "t2.small": 0.023, "t2.medium": 0.0464, "t2.large": 0.0928,
    "t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416, "t3.large": 0.0832,
    "t3.xlarge": 0.1664, "t3.2xlarge": 0.3328,
    "t3a.medium": 0.0376, "t3a.large": 0.0752,
    "t4g.micro": 0.0084, "t4g.small": 0.0168, "t4g.medium": 0.0336, "t4g.large": 0.0672,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384, "m5.4xlarge": 0.768,
    "m6i.large": 0.096, "m6i.xlarge": 0.192, "m6i.2xlarge": 0.384,
    "m6g.large": 0.077, "m6g.xlarge": 0.154,
    "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34,
    "c6i.large": 0.085, "c6i.xlarge": 0.17,
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
    "r6g.large": 0.1008, "r6g.xlarge": 0.2016,
}
DEFAULT_HOURLY = 0.05  # fall-back if type unknown (deliberately low)


def _max_cpu(cw, instance_id: str) -> float | None:
    """Max CPUUtilization over the lookback window, or None if no datapoints."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days())
    resp = cw.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Maximum"],
    )
    points = resp.get("Datapoints", [])
    if not points:
        return None
    return max(p["Maximum"] for p in points)


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ec2 = client("ec2", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        ):
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    inst_id = inst["InstanceId"]
                    try:
                        max_cpu = _max_cpu(cw, inst_id)
                    except ClientError:
                        continue
                    # No metrics at all == too new / no CW agent; don't guess.
                    if max_cpu is None or max_cpu >= CPU_IDLE_THRESHOLD_PCT:
                        continue

                    inst_type = inst.get("InstanceType", "")
                    hourly = EC2_HOURLY.get(inst_type, DEFAULT_HOURLY)
                    monthly = round(hourly * HOURS_PER_MONTH, 2)
                    arn = f"arn:aws:ec2:{region}:{account_id}:instance/{inst_id}"
                    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                    name_tag = tags.get("Name", inst_id)

                    # An instance launched by an Auto Scaling group can't simply
                    # be stopped — the ASG treats a stop as an unhealthy node and
                    # relaunches/replaces it, so the saving never materialises.
                    # The genuine fix is to lower the group's desired capacity or
                    # adjust its scaling policy. Surface that instead of a stop.
                    asg_name = tags.get("aws:autoscaling:groupName")
                    if asg_name:
                        cli_fix = (
                            f"# '{name_tag}' is managed by Auto Scaling group "
                            f"'{asg_name}'. Stopping it just triggers a replacement. "
                            "Reduce capacity instead, e.g.: "
                            f"aws autoscaling set-desired-capacity --region {region} "
                            f"--auto-scaling-group-name {asg_name} "
                            "--desired-capacity <lower-N>"
                        )
                        description = (
                            f"Instance {inst_id} is running (fully billed) but peaked at "
                            f"only {max_cpu:.1f}% CPU over the last {lookback_days()} days. "
                            f"only {max_cpu:.1f}% CPU over the last {LOOKBACK_DAYS} days. "
                            f"It belongs to Auto Scaling group '{asg_name}', so don't stop "
                            "it directly (the ASG would replace it). Lower the group's "
                            "desired capacity or tune its scaling policy. Savings shown is "
                            "one instance's full cost."
                        )
                        confidence = Confidence.LOW
                    else:
                        cli_fix = (
                            f"aws ec2 stop-instances --region {region} "
                            f"--instance-ids {inst_id}"
                        )
                        description = (
                            f"Instance {inst_id} is running (fully billed) but peaked at "
                            f"only {max_cpu:.1f}% CPU over the last {lookback_days()} days. "
                            f"only {max_cpu:.1f}% CPU over the last {LOOKBACK_DAYS} days. "
                            "Stop it if unused, or rightsize to a smaller type. The "
                            "savings shown is the full instance cost; rightsizing "
                            "recovers part of it."
                        )
                        confidence = Confidence.MEDIUM  # low CPU != definitely unused

                    findings.append(
                        Finding(
                            id=Finding.make_id(CHECK_ID, arn),
                            check_id=CHECK_ID,
                            title=(
                                f"Idle EC2 '{name_tag}' ({inst_type}), "
                                f"max {max_cpu:.1f}% CPU over {lookback_days()}d"
                                f"max {max_cpu:.1f}% CPU over {LOOKBACK_DAYS}d"
                            ),
                            description=description,
                            service="ec2",
                            region=region,
                            resource_arn=arn,
                            resource_id=inst_id,
                            monthly_savings_usd=monthly,
                            severity=Severity.from_monthly_usd(monthly),
                            confidence=confidence,
                            cli_fix_command=cli_fix,
                            fix_destructive=False,  # stop is reversible; data on EBS survives
                            evidence={
                                "instance_type": inst_type,
                                "max_cpu_pct_7d": round(max_cpu, 2),
                                "auto_scaling_group": asg_name,
                                "launch_time": inst.get("LaunchTime").isoformat()
                                if inst.get("LaunchTime")
                                else None,
                                "tags": tags,
                            },
                        )
                    )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    return findings
