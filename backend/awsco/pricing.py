"""Hardcoded AWS pricing for v1 (US East 1, on-demand, USD).

Long-term plan: call the AWS Pricing API per region. For v1 we use conservative
us-east-1 list prices. Underestimating waste is fine; overestimating is not.
"""

# EBS storage ($/GB-month)
EBS_GP2_GB_MONTH = 0.10
EBS_GP3_GB_MONTH = 0.08
EBS_IO1_GB_MONTH = 0.125
EBS_ST1_GB_MONTH = 0.045
EBS_SC1_GB_MONTH = 0.015

# Provisioned IOPS ($/IOPS-month). gp3 includes 3,000 IOPS; io1 bills every one.
EBS_IO1_IOPS_MONTH = 0.065
EBS_GP3_IOPS_MONTH = 0.005
GP3_BASELINE_IOPS = 3000
GP3_MAX_IOPS = 16000

# Snapshots ($/GB-month, standard tier)
EBS_SNAPSHOT_GB_MONTH = 0.05

# Public IPv4 — since Feb 2024 every public IPv4 (including unattached EIP) costs
# $0.005/hour, regardless of whether attached or not.
PUBLIC_IPV4_HOURLY = 0.005
PUBLIC_IPV4_MONTHLY = PUBLIC_IPV4_HOURLY * 24 * 30  # ~$3.60

# NAT Gateway hourly + per-GB (we only count hourly idle cost; data charges are
# already captured by usage absent)
NAT_GATEWAY_HOURLY = 0.045
NAT_GATEWAY_MONTHLY = NAT_GATEWAY_HOURLY * 24 * 30  # ~$32.40

# Load balancers (idle hourly cost; LCU charges are zero when idle)
ALB_HOURLY = 0.0225
NLB_HOURLY = 0.0225
LB_MONTHLY = ALB_HOURLY * 24 * 30  # ~$16.20

# CloudWatch Logs ($/GB)
CLOUDWATCH_LOGS_INGEST_GB = 0.50
CLOUDWATCH_LOGS_STORAGE_GB_MONTH = 0.03

# RDS manual snapshot / backup storage beyond the free tier ($/GB-month).
RDS_SNAPSHOT_GB_MONTH = 0.095

# S3 Standard storage ($/GB-month, first 50 TB tier, us-east-1). Used to price
# the orphaned data left behind by incomplete multipart uploads.
S3_STANDARD_GB_MONTH = 0.023

# DynamoDB provisioned capacity ($/hour per unit, us-east-1).
DYNAMODB_RCU_HOURLY = 0.00013
DYNAMODB_WCU_HOURLY = 0.00065

# Networking ($/hour -> monthly). Interface endpoints bill per AZ.
VPC_INTERFACE_ENDPOINT_AZ_MONTHLY = round(0.01 * 24 * 30, 2)  # ~$7.20
TGW_ATTACHMENT_MONTHLY = round(0.05 * 24 * 30, 2)  # ~$36.00
VPN_CONNECTION_MONTHLY = round(0.05 * 24 * 30, 2)  # ~$36.00

# Secrets Manager ($/secret-month).
SECRETS_MANAGER_SECRET_MONTH = 0.40

HOURS_PER_MONTH = 24 * 30


def dynamodb_provisioned_monthly_cost(rcu: int, wcu: int) -> float:
    """Monthly cost of provisioned read/write capacity units."""
    hourly = rcu * DYNAMODB_RCU_HOURLY + wcu * DYNAMODB_WCU_HOURLY
    return round(hourly * HOURS_PER_MONTH, 2)


def ebs_volume_monthly_cost(volume_type: str, size_gb: int) -> float:
    """Estimate monthly cost for an EBS volume."""
    rates = {
        "gp2": EBS_GP2_GB_MONTH,
        "gp3": EBS_GP3_GB_MONTH,
        "io1": EBS_IO1_GB_MONTH,
        "io2": EBS_IO1_GB_MONTH,
        "st1": EBS_ST1_GB_MONTH,
        "sc1": EBS_SC1_GB_MONTH,
        "standard": EBS_GP2_GB_MONTH,  # magnetic, legacy
    }
    rate = rates.get(volume_type, EBS_GP2_GB_MONTH)
    return round(rate * size_gb, 2)


def gp2_to_gp3_monthly_savings(size_gb: int) -> float:
    """gp3 is 20% cheaper than gp2 at the same size."""
    return round((EBS_GP2_GB_MONTH - EBS_GP3_GB_MONTH) * size_gb, 2)


def io1_monthly_cost(size_gb: int, iops: int) -> float:
    return round(EBS_IO1_GB_MONTH * size_gb + EBS_IO1_IOPS_MONTH * iops, 2)


def gp3_monthly_cost(size_gb: int, iops: int) -> float:
    """gp3 at the same IOPS (throughput left at the free 125 MB/s baseline)."""
    extra_iops = max(0, iops - GP3_BASELINE_IOPS)
    return round(EBS_GP3_GB_MONTH * size_gb + EBS_GP3_IOPS_MONTH * extra_iops, 2)
