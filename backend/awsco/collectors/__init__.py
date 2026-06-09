"""Per-resource waste collectors.

Each module exposes a `collect(region: str, profile: str | None) -> list[Finding]`.
Collectors must:
- never make Modify*/Delete*/Create* calls,
- gracefully handle AccessDenied / OptInRequired,
- be safe to run concurrently across regions.
"""

from awsco.collectors import (
    ce_anomalies,
    ce_ri_recommendations,
    ce_savings_plans,
    cloudwatch_logs_no_retention,
    compute_optimizer_rightsizing,
    dynamodb_idle,
    ebs_gp2_to_gp3,
    ebs_snapshots_old,
    ebs_unattached,
    ec2_idle,
    ec2_stopped_billed_ebs,
    eip_unused,
    elasticache_idle,
    lb_unused,
    nat_idle,
    rds_idle,
    rds_snapshots_old,
    redshift_idle,
)

ALL_COLLECTORS = [
    ebs_unattached,
    eip_unused,
    ebs_snapshots_old,
    nat_idle,
    ec2_idle,
    ec2_stopped_billed_ebs,
    rds_idle,
    rds_snapshots_old,
    lb_unused,
    ebs_gp2_to_gp3,
    cloudwatch_logs_no_retention,
    dynamodb_idle,
    elasticache_idle,
    redshift_idle,
    # FinOps recommendations (rightsizing / commitments / anomalies)
    compute_optimizer_rightsizing,
    ce_ri_recommendations,
    ce_savings_plans,
    ce_anomalies,
]
