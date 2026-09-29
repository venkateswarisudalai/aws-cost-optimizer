"""Plain-language guidance for acting on each finding.

Every finding gets the same four answers, whatever check produced it:
  - recommendation:  what to change it to
  - risks:           what could break (downtime, data loss, performance, lock-in)
  - before_you_act:  the checks / backups to do first
  - undo:            how to reverse it — or a clear statement that you can't

plus a single `risk_level` so the dashboard can sort safe wins from changes
that need review. Guidance lives here, keyed by check_id, rather than in each
collector, so the wording stays consistent and one file holds every caveat.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from awsco.models import Finding


class RiskLevel(str, Enum):
    SAFE = "safe"                # no downtime, no data loss, easy to reverse
    RESTART = "restart"          # brief downtime or a behaviour change; reversible
    DESTRUCTIVE = "destructive"  # deletes data or something that can't be recreated as-is
    COMMITMENT = "commitment"    # a 1–3 year financial commitment
    INFO = "info"                # nothing to apply — investigate


class Guidance(BaseModel):
    recommendation: str
    risk_level: RiskLevel
    risks: list[str] = Field(default_factory=list)
    before_you_act: list[str] = Field(default_factory=list)
    undo: str
    reversible: bool


def _ev(f: Finding, key: str, default: Any = None) -> Any:
    return (f.evidence or {}).get(key, default)


def _snapshot_first_cmd(f: Finding) -> str:
    return (
        f"aws ec2 create-snapshot --region {f.region} --volume-id {f.resource_id} "
        f"--description 'awsco backup before delete'"
    )


# --- per-check guidance --------------------------------------------------------


def _ebs_unattached(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the volume. If you might need the data, snapshot it first — "
        "a snapshot costs about half as much as the volume.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "All data on the volume is permanently deleted.",
            "It may be a deliberately detached volume (e.g. a DR copy or one kept for a "
            "later re-attach).",
        ],
        before_you_act=[
            "Check the volume's tags and name for an owner.",
            f"Snapshot it: `{_snapshot_first_cmd(f)}`",
        ],
        undo="Only via a snapshot taken beforehand: `aws ec2 create-volume "
        "--snapshot-id <snap-id> --availability-zone <az>`. Without one, it's gone.",
        reversible=False,
    )


def _eip_unused(f: Finding) -> Guidance:
    ip = _ev(f, "public_ip", "this address")
    return Guidance(
        recommendation=f"Release {ip} if nothing depends on this exact IP.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Once released, you usually can't get the same IP back.",
            "Partner firewall allowlists, DNS records or email SPF entries that name "
            f"{ip} will stop working.",
        ],
        before_you_act=[
            f"Search your DNS (Route 53 and elsewhere) and allowlists for {ip}.",
            "Ask whether it's reserved for a failover or a planned launch.",
        ],
        undo=f"Best effort only: `aws ec2 allocate-address --region {f.region} --address {ip}` "
        "works only if no one else has been given the IP since.",
        reversible=False,
    )


def _ebs_snapshot_old(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the snapshot, or move it to the Archive tier (about 75% "
        "cheaper) if you must keep it: `aws ec2 modify-snapshot-tier --snapshot-id "
        f"{f.resource_id} --storage-tier archive`.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Deletion is permanent — the restore point is gone.",
            "Snapshots are incremental: the real saving can be smaller than the "
            "estimate if later snapshots share its blocks.",
            "It may be needed for compliance or audit retention.",
        ],
        before_you_act=[
            "Check your retention policy (SOC 2 / legal hold) for this data.",
            "Check it isn't the source of an AMI still in use (AWS blocks that delete).",
        ],
        undo="None once deleted. Archiving instead is reversible "
        "(`restore-snapshot-tier`, takes 24–72 hours).",
        reversible=False,
    )


def _nat_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the NAT gateway if no private subnet needs outbound "
        "internet. For AWS-only traffic (S3, DynamoDB) a free gateway endpoint does the job.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Anything in a private subnet routed through it loses internet access — "
            "package installs, external API calls and patching will fail.",
            "Its public IP changes if you recreate it, which breaks partner allowlists.",
        ],
        before_you_act=[
            "Find route tables that point at it: `aws ec2 describe-route-tables "
            f"--region {f.region} --filters Name=route.nat-gateway-id,Values={f.resource_id}`.",
            "Keep its Elastic IP (don't release it) so a rebuild can reuse the address.",
        ],
        undo="Recreate with `aws ec2 create-nat-gateway` (reusing the kept Elastic IP) and "
        "point the route tables back at it. Expect an outage in between.",
        reversible=True,
    )


def _ec2_idle(f: Finding) -> Guidance:
    asg = _ev(f, "auto_scaling_group")
    risks = [
        "Whatever runs on it stops until someone starts it again.",
        "Its public IP changes on restart, unless it has an Elastic IP.",
        "Any instance-store (ephemeral) disk is wiped. EBS data is kept.",
    ]
    if asg:
        risks.insert(0, f"It belongs to Auto Scaling group '{asg}', which will just launch a "
                     "replacement — lower the group's desired capacity instead.")
    return Guidance(
        recommendation="Stop the instance (EBS storage is still billed while stopped). If "
        "it stays unneeded, snapshot it as an AMI and terminate it.",
        risk_level=RiskLevel.RESTART,
        risks=risks,
        before_you_act=[
            "Low CPU isn't proof of no use: check network traffic and who owns it (tags).",
            "Check for batch jobs that only run monthly.",
        ],
        undo=f"`aws ec2 start-instances --region {f.region} --instance-ids {f.resource_id}`.",
        reversible=True,
    )


def _ec2_stopped_billed_ebs(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Create an AMI as a backup, then terminate the instance so its "
        "volumes stop billing.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Terminating deletes root volumes (and any set to DeleteOnTermination).",
            "The instance ID, private IP and any instance-specific config are gone for good.",
        ],
        before_you_act=[
            f"Back it up: `aws ec2 create-image --region {f.region} --instance-id "
            f"{f.resource_id} --name awsco-backup-{f.resource_id}` (the AMI's snapshots "
            "cost less than live volumes).",
            "Check whether it was stopped on purpose, e.g. a standby box.",
        ],
        undo="Launch a new instance from the AMI. The new one gets a different ID and IP.",
        reversible=False,
    )


def _rds_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Stop the instance for now. If it's truly retired, take a final "
        "snapshot and delete it — AWS restarts a stopped RDS instance after 7 days.",
        risk_level=RiskLevel.RESTART,
        risks=[
            "Apps with its connection string will fail while it's stopped.",
            "AWS automatically starts a stopped instance again after 7 days, so the "
            "saving isn't permanent.",
            "Storage and backups are still billed while it's stopped.",
        ],
        before_you_act=[
            "Confirm no app, cron job or BI tool still connects to it.",
            f"Take a snapshot: `aws rds create-db-snapshot --region {f.region} "
            f"--db-instance-identifier {f.resource_id} --db-snapshot-identifier "
            f"awsco-{f.resource_id}`.",
        ],
        undo=f"`aws rds start-db-instance --region {f.region} --db-instance-identifier "
        f"{f.resource_id}` (takes a few minutes).",
        reversible=True,
    )


def _rds_snapshot_old(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the manual snapshot if it's past your retention requirement.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Permanent: it may be the only copy of a database that no longer exists.",
            "It may be under a compliance or legal retention requirement.",
        ],
        before_you_act=[
            f"Check whether the source database ({_ev(f, 'source_db', 'unknown')}) still exists.",
            "If unsure, export it to S3 (much cheaper, Parquet): `aws rds "
            "start-export-task`.",
        ],
        undo="None once deleted.",
        reversible=False,
    )


def _lb_unused(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the load balancer.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Its DNS name is gone for good; a recreated one gets a new name, so "
            "any CNAME or alias pointing at it breaks.",
            "Its listener rules and TLS certificate bindings are lost.",
        ],
        before_you_act=[
            "Search Route 53 and other DNS for records pointing at its DNS name.",
            "Save its config: `aws elbv2 describe-listeners --load-balancer-arn "
            f"{f.resource_arn}` and `describe-rules`.",
        ],
        undo="Recreate it from the saved config and update DNS to the new name.",
        reversible=False,
    )


def _gp2_to_gp3(f: Finding) -> Guidance:
    size = int(_ev(f, "size_gb", 0) or 0)
    gp2_iops = min(max(size * 3, 100), 16000)
    risks = [
        "The same volume can't be modified again for 6 hours afterwards.",
        "gp3 starts at 125 MB/s of throughput; gp2 bursts up to 250 MB/s on large volumes.",
    ]
    before = ["Nothing to stop or detach: the change is applied online."]
    if gp2_iops > 3000:
        risks.insert(0, f"At {size} GB this gp2 volume gets {gp2_iops} IOPS; plain gp3 gives "
                        "3,000. Without adding IOPS it will be slower.")
        before.append(f"Keep the performance: add `--iops {gp2_iops} --throughput 250` "
                      "(still cheaper than gp2).")
    return Guidance(
        recommendation="Change the volume type to gp3 in place.",
        risk_level=RiskLevel.SAFE,
        risks=risks,
        before_you_act=before,
        undo=f"`aws ec2 modify-volume --region {f.region} --volume-id {f.resource_id} "
        "--volume-type gp2` after the 6-hour cooldown.",
        reversible=True,
    )


def _io1_to_gp3(f: Finding) -> Guidance:
    return Guidance(
        recommendation=f"Change to gp3 with the same {_ev(f, 'iops', '')} IOPS.",
        risk_level=RiskLevel.SAFE,
        risks=[
            "io1 has steadier sub-millisecond latency; latency-sensitive databases "
            "may notice the difference.",
            "The same volume can't be modified again for 6 hours afterwards.",
        ],
        before_you_act=[
            "For a production database, try it on a replica or during a quiet period first.",
            "Match throughput if the workload needs more than 125 MB/s (`--throughput`).",
        ],
        undo=f"`aws ec2 modify-volume --region {f.region} --volume-id {f.resource_id} "
        f"--volume-type io1 --iops {_ev(f, 'iops', '<iops>')}` after the 6-hour cooldown.",
        reversible=True,
    )


def _logs_no_retention(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Set a retention period (30 days in the fix command; choose what "
        "your compliance policy requires).",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Log events older than the retention period are permanently deleted, "
            "shortly after you apply it.",
            "Audit or security logs may need a year or more (e.g. SOC 2, PCI).",
        ],
        before_you_act=[
            "Check what retention your policies require for this log group.",
            "Archive old logs to S3 first if you need them: `aws logs create-export-task`.",
        ],
        undo="Retention can be raised or removed at any time, but already-deleted "
        "events can't be recovered.",
        reversible=False,
    )


def _dynamodb_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Switch the table to on-demand (pay per request) billing.",
        risk_level=RiskLevel.SAFE,
        risks=[
            "If traffic later grows steadily, on-demand can cost more than provisioned.",
            "You can switch billing modes back only once every 24 hours.",
        ],
        before_you_act=["Check for scheduled bulk jobs that hit the table rarely but hard."],
        undo=f"`aws dynamodb update-table --region {f.region} --table-name {f.resource_id} "
        "--billing-mode PROVISIONED --provisioned-throughput "
        f"ReadCapacityUnits={_ev(f, 'read_capacity_units', '<rcu>')},"
        f"WriteCapacityUnits={_ev(f, 'write_capacity_units', '<wcu>')}`.",
        reversible=True,
    )


def _elasticache_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the cluster, taking a final snapshot (Redis/Valkey).",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "All cached data is lost. Memcached has no snapshots at all.",
            "Apps that expect the cache may slow down or error, rather than fall back.",
            "The endpoint hostname changes if you recreate it.",
        ],
        before_you_act=[
            "Confirm no app config references its endpoint.",
            "For Redis/Valkey, add `--final-snapshot-identifier awsco-final` to the delete.",
        ],
        undo="Recreate from the final snapshot (Redis/Valkey) and update app config "
        "to the new endpoint.",
        reversible=False,
    )


def _redshift_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Pause the cluster. Only storage is billed while it's paused.",
        risk_level=RiskLevel.RESTART,
        risks=[
            "Queries and dashboards fail until it's resumed.",
            "Scheduled loads (ETL) that write to it will fail while it's paused.",
        ],
        before_you_act=["Check scheduled queries and ETL jobs that write to it."],
        undo=f"`aws redshift resume-cluster --region {f.region} --cluster-identifier "
        f"{f.resource_id}` (takes a few minutes).",
        reversible=True,
    )


def _opensearch_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the domain after taking a manual snapshot to S3.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "All indices are permanently deleted. AWS's automated snapshots are "
            "deleted with the domain.",
            "The endpoint changes if you recreate it.",
        ],
        before_you_act=[
            "Register an S3 snapshot repository and take a manual snapshot.",
            "Confirm no log shipper (Fluent Bit, Logstash) still sends to it.",
        ],
        undo="Create a new domain and restore the manual snapshot from S3.",
        reversible=False,
    )


def _s3_multipart(f: Finding) -> Guidance:
    bucket = _ev(f, "bucket", f.resource_id)
    return Guidance(
        recommendation="Add a lifecycle rule that aborts incomplete uploads after 7 days.",
        risk_level=RiskLevel.SAFE,
        risks=[
            "This command REPLACES the bucket's whole lifecycle configuration. Any "
            "existing rules (expiry, tiering) are wiped unless you merge them in.",
            "A genuinely slow, still-running upload older than 7 days would be aborted.",
        ],
        before_you_act=[
            "Save the current rules first: `aws s3api get-bucket-lifecycle-configuration "
            f"--bucket {bucket}` and add the abort rule to that JSON.",
        ],
        undo="Re-apply the saved lifecycle JSON with `put-bucket-lifecycle-configuration`. "
        "Parts that were already aborted can't be recovered.",
        reversible=True,
    )


def _secret_unused(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Schedule deletion with a recovery window.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "Anything that still reads it (a rarely run job, DR runbook) will fail.",
            "After the recovery window ends, the value is gone for good.",
        ],
        before_you_act=[
            "Search CloudTrail for GetSecretValue on this secret.",
            "Use a longer recovery window (up to 30 days) for anything important.",
        ],
        undo=f"Within the recovery window: `aws secretsmanager restore-secret --region "
        f"{f.region} --secret-id {f.resource_arn}`.",
        reversible=True,
    )


def _ec2_rightsizing(f: Finding) -> Guidance:
    target = _ev(f, "recommended_instance_type", "the recommended type")
    current = _ev(f, "current_instance_type", "the current type")
    risk = _ev(f, "performance_risk")
    risks = [
        "Needs a stop/start, which means a few minutes of downtime.",
        "Its public IP changes, unless it has an Elastic IP.",
        "A smaller type has less headroom for traffic spikes.",
    ]
    if isinstance(risk, (int, float)) and risk >= 2:
        risks.insert(0, f"Compute Optimizer rates the performance risk {risk}/4, so test "
                        "it before relying on it.")
    return Guidance(
        recommendation=f"Resize from {current} to {target}.",
        risk_level=RiskLevel.RESTART,
        risks=risks,
        before_you_act=[
            "Check peak (not average) CPU and memory, including month-end or seasonal peaks.",
            f"Confirm {target} supports the same architecture (x86 vs ARM) and features.",
            "Do it in a maintenance window, or behind a load balancer one instance at a time.",
        ],
        undo=f"Stop the instance, set the type back to {current}, and start it again.",
        reversible=True,
    )


def _ri(f: Finding) -> Guidance:
    breakeven = _ev(f, "estimated_break_even_months")
    upfront = _ev(f, "upfront_cost_usd")
    risks = [
        "You pay for the full term even if you stop using the instances.",
        "It only covers the exact instance family, region and engine it's bought for.",
    ]
    if upfront:
        risks.append(f"Needs about ${float(upfront):,.0f} upfront.")
    before = ["Confirm this usage will run steadily for the whole term (no planned migration "
              "or shutdown)."]
    if breakeven:
        before.append(f"Estimated break-even: {breakeven} months.")
    return Guidance(
        recommendation="Buy the recommended Reserved Instances (1-year, as priced here).",
        risk_level=RiskLevel.COMMITMENT,
        risks=risks,
        before_you_act=before + ["Apply rightsizing and cleanup first, so you don't reserve "
                                 "capacity you're about to remove."],
        undo="Can't be cancelled. Standard EC2 RIs can be listed on the RI Marketplace; "
        "RDS, ElastiCache and other RIs can't be resold.",
        reversible=False,
    )


def _savings_plan(f: Finding) -> Guidance:
    hourly = _ev(f, "hourly_commitment_usd", "?")
    return Guidance(
        recommendation=f"Buy a Savings Plan committing ${hourly}/hour for 1 year.",
        risk_level=RiskLevel.COMMITMENT,
        risks=[
            f"You pay ${hourly}/hour for the whole term, even if usage drops.",
            "Overlaps with Reserved Instances covering the same usage — don't buy both.",
        ],
        before_you_act=[
            "Apply rightsizing and idle cleanup first; they lower the baseline you should "
            "commit to.",
            "Commit to less than the recommendation if usage might fall.",
        ],
        undo="Generally can't be cancelled or resold. AWS allows returning a recent "
        "purchase within 7 days, with limits — check the current terms before buying.",
        reversible=False,
    )


def _anomaly(f: Finding) -> Guidance:
    return Guidance(
        recommendation=f"Investigate the spike in {_ev(f, 'root_cause_service', 'this service')}.",
        risk_level=RiskLevel.INFO,
        risks=["Nothing is changed. A real spike may mean a runaway job, a leaked key or "
               "a misconfiguration."],
        before_you_act=["Open the anomaly in Cost Explorer and check the root causes it lists."],
        undo="Not applicable.",
        reversible=True,
    )


def _coh(f: Finding) -> Guidance:
    action = _ev(f, "action_type", "")
    restart = _ev(f, "restart_needed")
    rollback = _ev(f, "rollback_possible")
    current, target = _ev(f, "current", ""), _ev(f, "recommended", "")
    rec = f"{action or 'Apply the recommendation'}"
    if current and target and current != target:
        rec += f": {current} → {target}"

    if action in {"PurchaseSavingsPlans", "PurchaseReservedInstances"}:
        level = RiskLevel.COMMITMENT
    elif action == "Delete" or rollback is False:
        level = RiskLevel.DESTRUCTIVE
    elif restart or action in {"Stop", "Rightsize", "MigrateToGraviton", "ScaleIn"}:
        level = RiskLevel.RESTART
    else:
        level = RiskLevel.SAFE

    risks = []
    if restart:
        risks.append("Needs a restart (brief downtime).")
    if rollback is False:
        risks.append("AWS marks this as not reversible.")
    if action == "MigrateToGraviton":
        risks.append("Graviton is ARM: every binary, container image and native library "
                     "must have an ARM64 build.")
    if level == RiskLevel.COMMITMENT:
        risks.append("A 1–3 year financial commitment that generally can't be cancelled.")
    if action == "Delete":
        risks.append("Deletes the resource and its data.")
    if not risks:
        risks.append("Low risk, but check the recommendation's details in the console.")

    before = ["Open the recommendation in Cost Optimization Hub and check its lookback "
              "period and details."]
    if _ev(f, "implementation_effort"):
        before.append(f"AWS rates the effort as {_ev(f, 'implementation_effort')}.")
    if action == "MigrateToGraviton":
        before.append("Test the workload on an ARM instance first.")

    if level == RiskLevel.COMMITMENT:
        undo = "Generally can't be undone — see the Savings Plan / RI terms."
    elif rollback is False or action == "Delete":
        undo = "Not reversible — back up first."
    elif current:
        undo = f"Change it back to {current}."
    else:
        undo = "Reverse the change in the console."

    return Guidance(
        recommendation=rec,
        risk_level=level,
        risks=risks,
        before_you_act=before,
        undo=undo,
        reversible=level not in {RiskLevel.DESTRUCTIVE, RiskLevel.COMMITMENT},
    )


def _vpc_endpoint_idle(f: Finding) -> Guidance:
    svc = _ev(f, "service_name", "the service")
    risks = [
        f"If anything in the VPC still calls {svc}, it will either go out through the "
        "NAT/internet (costing data charges) or fail if there's no internet route.",
    ]
    if _ev(f, "private_dns_enabled"):
        risks.append("Private DNS is on: the service's normal hostname resolves to this "
                     "endpoint today, so removing it changes where that traffic goes.")
    if not _ev(f, "metrics_found"):
        risks.append("CloudWatch had no metrics for it at all — weaker evidence than a "
                     "measured zero.")
    return Guidance(
        recommendation="Delete the interface endpoint.",
        risk_level=RiskLevel.RESTART,
        risks=risks,
        before_you_act=[
            "Check whether private subnets have a NAT or internet route to fall back on.",
            "Confirm no endpoint policy is part of a compliance control (data-perimeter setups).",
        ],
        undo=f"Recreate it: `aws ec2 create-vpc-endpoint --vpc-endpoint-type Interface "
        f"--vpc-id {_ev(f, 'vpc_id', '<vpc>')} --service-name {svc} --subnet-ids ...`. "
        "It gets a new ID and DNS names.",
        reversible=True,
    )


def _tgw_attachment_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the Transit Gateway attachment.",
        risk_level=RiskLevel.RESTART,
        risks=[
            "Routes through the Transit Gateway to and from this network stop working.",
            "It may be a standby path for failover that's idle by design.",
        ],
        before_you_act=[
            "Check the Transit Gateway route tables for routes that use this attachment.",
            "Check whether a network team owns it (shared via Resource Access Manager).",
        ],
        undo="Recreate the attachment and re-add its route-table associations and "
        "propagations. It gets a new ID.",
        reversible=True,
    )


def _vpn_idle(f: Finding) -> Guidance:
    return Guidance(
        recommendation="Delete the VPN connection. Also delete its customer gateway if "
        "nothing else uses it.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=[
            "The on-premises site loses its private link into AWS.",
            "A recreated VPN gets new tunnel IPs and pre-shared keys, so the office "
            "router must be reconfigured.",
            "It may be a backup link that only carries traffic during an outage.",
        ],
        before_you_act=[
            "Ask the network owner whether the site it connects to still exists.",
            "Save the configuration: download it from the VPN console.",
        ],
        undo="Recreate it and reconfigure the customer's router with the new tunnel "
        "details.",
        reversible=False,
    )


def _vpc_abandoned(f: Finding) -> Guidance:
    risks = [
        "Everything in the VPC is removed. Anything you missed stops working, and "
        "load balancer DNS names and NAT IPs can't be recovered.",
        "It may be a disaster-recovery VPC that's quiet by design.",
    ]
    before = [
        "Check the VPC's tags and CloudFormation/Terraform state for an owner. If it's "
        "managed by IaC, tear it down there instead (`terraform destroy`, delete the stack).",
        "Check Route 53 for records that point at its load balancers.",
    ]
    peerings = _ev(f, "active_peering_connections") or []
    if peerings:
        risks.append(f"It has active peering ({', '.join(peerings)}): another VPC may "
                     "rely on routes through it.")
        before.append("Check the peered VPCs' route tables before deleting anything.")
    if _ev(f, "tgw_attachments"):
        risks.append("It's attached to a Transit Gateway, so other networks may route to it.")
    if not _ev(f, "flow_logs_enabled"):
        before.append("No flow logs are enabled, so traffic was judged from NAT, load "
                      "balancer and endpoint metrics only. For certainty, turn on flow logs "
                      "for a week first.")
    before.append("Run the teardown one step at a time, top to bottom, and wait for each "
                  "step to finish.")
    return Guidance(
        recommendation="Tear down the VPC's billable infrastructure (and then the VPC). "
        "If you're not sure, delete just the NAT gateways first — that's most of the cost "
        "and is easy to recreate.",
        risk_level=RiskLevel.DESTRUCTIVE,
        risks=risks,
        before_you_act=before,
        undo="No single undo. Rebuild from infrastructure-as-code if it has any; "
        "otherwise each resource must be recreated by hand with new IDs, IPs and DNS names.",
        reversible=False,
    )


def _sg_unused(f: Finding) -> Guidance:
    world = _ev(f, "open_to_world") or []
    risks = [
        "A launch template, Auto Scaling group or CloudFormation stack may reference it "
        "without any running interface using it yet. Their next launch would fail.",
    ]
    if world:
        risks.insert(0, f"It allows inbound traffic from anywhere ({', '.join(world)}). "
                        "Leaving it around risks someone attaching it to a new instance.")
    return Guidance(
        recommendation="Delete the security group. It saves $0 but removes attack surface.",
        risk_level=RiskLevel.SAFE,
        risks=risks,
        before_you_act=[
            "Check launch templates: `aws ec2 describe-launch-template-versions "
            "--versions '$Latest' --launch-template-id <id>` (or search your IaC for "
            f"{f.resource_id}).",
            f"Save its rules: `aws ec2 describe-security-groups --group-ids {f.resource_id}`.",
        ],
        undo="Recreate it from the saved rules. It gets a new group ID, so anything that "
        "named the old ID must be updated.",
        reversible=True,
    )


_BUILDERS: dict[str, Callable[[Finding], Guidance]] = {
    "ebs.unattached": _ebs_unattached,
    "eip.unused": _eip_unused,
    "ebs.snapshot-old": _ebs_snapshot_old,
    "nat.idle": _nat_idle,
    "ec2.idle": _ec2_idle,
    "ec2.stopped-billed-ebs": _ec2_stopped_billed_ebs,
    "rds.idle": _rds_idle,
    "rds.snapshot-old": _rds_snapshot_old,
    "lb.unused": _lb_unused,
    "ebs.gp2-to-gp3": _gp2_to_gp3,
    "ebs.io1-to-gp3": _io1_to_gp3,
    "logs.no-retention": _logs_no_retention,
    "dynamodb.idle-provisioned": _dynamodb_idle,
    "elasticache.idle": _elasticache_idle,
    "redshift.idle": _redshift_idle,
    "opensearch.idle": _opensearch_idle,
    "s3.incomplete-multipart-upload": _s3_multipart,
    "secretsmanager.unused": _secret_unused,
    "ec2.rightsizing": _ec2_rightsizing,
    "ce.ri-recommendation": _ri,
    "ce.savings-plan": _savings_plan,
    "ce.anomaly": _anomaly,
    "coh.recommendation": _coh,
    "vpc.endpoint-idle": _vpc_endpoint_idle,
    "tgw.attachment-idle": _tgw_attachment_idle,
    "vpn.idle": _vpn_idle,
    "vpc.abandoned": _vpc_abandoned,
    "sg.unused": _sg_unused,
}


def _fallback(f: Finding) -> Guidance:
    return Guidance(
        recommendation=f.title,
        risk_level=RiskLevel.DESTRUCTIVE if f.fix_destructive else RiskLevel.RESTART,
        risks=["Deletes data." if f.fix_destructive else "Review the change before applying it."],
        before_you_act=["Confirm the resource's owner and that it's unused."],
        undo="Not reversible — back up first." if f.fix_destructive else "Reverse the change manually.",
        reversible=not f.fix_destructive,
    )


def guidance_for(f: Finding) -> Guidance:
    return _BUILDERS.get(f.check_id, _fallback)(f)


def attach_guidance(findings: list[Finding]) -> list[Finding]:
    for f in findings:
        f.guidance = guidance_for(f).model_dump(mode="json")
    return findings
