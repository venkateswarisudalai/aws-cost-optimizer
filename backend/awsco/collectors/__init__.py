"""Per-resource waste collectors.

Each module exposes a `collect(region: str, profile: str | None) -> list[Finding]`.
Collectors must:
- never make Modify*/Delete*/Create* calls,
- gracefully handle AccessDenied / OptInRequired,
- be safe to run concurrently across regions.
"""

from awsco.collectors import (
    cloudwatch_logs_no_retention,
    ebs_gp2_to_gp3,
    ebs_snapshots_old,
    ebs_unattached,
    ec2_stopped_billed_ebs,
    eip_unused,
    lb_unused,
    nat_idle,
    rds_idle,
)

ALL_COLLECTORS = [
    ebs_unattached,
    eip_unused,
    ebs_snapshots_old,
    nat_idle,
    ec2_stopped_billed_ebs,
    rds_idle,
    lb_unused,
    ebs_gp2_to_gp3,
    cloudwatch_logs_no_retention,
]
