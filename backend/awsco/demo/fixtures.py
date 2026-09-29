"""Realistic fake findings for the --demo-data mode."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from awsco.models import Category, Confidence, Finding, ScanResult, Severity
from awsco.guidance import attach_guidance
from awsco.regions import commercial_regions
from awsco.scanner import mark_overlaps, roll_up_vpcs


def _f(
    check_id: str,
    title: str,
    description: str,
    service: str,
    region: str,
    resource_id: str,
    monthly: float,
    confidence: Confidence,
    cli: str,
    destructive: bool,
    evidence: dict,
    category: Category = Category.WASTE,
) -> Finding:
    arn = f"arn:aws:{service}:{region}:123456789012:demo/{resource_id}"
    return Finding(
        id=Finding.make_id(check_id, arn),
        check_id=check_id,
        title=title,
        description=description,
        service=service,
        region=region,
        resource_arn=arn,
        resource_id=resource_id,
        monthly_savings_usd=monthly,
        category=category,
        severity=Severity.from_monthly_usd(monthly),
        confidence=confidence,
        cli_fix_command=cli,
        fix_destructive=destructive,
        evidence=evidence,
    )


DEMO_SPEND = {
    "period_start": "2026-05-02",
    "period_end": "2026-06-01",
    "total_30d_usd": 4812.37,
    "by_service": [
        {"service": "Amazon Elastic Compute Cloud - Compute", "cost_usd": 1896.20},
        {"service": "Amazon Relational Database Service", "cost_usd": 902.14},
        {"service": "EC2 - Other", "cost_usd": 611.08},
        {"service": "Amazon Simple Storage Service", "cost_usd": 488.51},
        {"service": "Amazon Virtual Private Cloud", "cost_usd": 263.40},
        {"service": "Amazon ElastiCache", "cost_usd": 214.66},
        {"service": "AmazonCloudWatch", "cost_usd": 176.93},
        {"service": "Elastic Load Balancing", "cost_usd": 121.50},
        {"service": "Other", "cost_usd": 137.95},
    ],
    "month_to_date_usd": 4812.37,
    "forecast_month_usd": 4990.00,
    "currency": "USD",
    "source": "cost-explorer",
}


def build_demo_scan() -> ScanResult:
    now = datetime.now(timezone.utc)
    findings = [
        _f(
            "nat.idle", "Idle NAT gateway nat-0a1b2c3d4e5f6",
            "Idle NAT gateway in us-east-1, 0 bytes over 7d.",
            "ec2", "us-east-1", "nat-0a1b2c3d4e5f6",
            32.40, Confidence.HIGH,
            "aws ec2 delete-nat-gateway --region us-east-1 --nat-gateway-id nat-0a1b2c3d4e5f6",
            False, {
                "bytes_out_7d": 0, "vpc_id": "vpc-aaa", "subnet_id": "subnet-bbb",
                "create_time": (now - timedelta(days=63)).isoformat(),
            },
        ),
        _f(
            "nat.idle", "Idle NAT gateway nat-99887766",
            "Idle NAT gateway in eu-west-1, 412 bytes over 7d.",
            "ec2", "eu-west-1", "nat-99887766",
            32.40, Confidence.HIGH,
            "aws ec2 delete-nat-gateway --region eu-west-1 --nat-gateway-id nat-99887766",
            False, {"bytes_out_7d": 412, "vpc_id": "vpc-ccc"},
        ),
        _f(
            "rds.idle", "Idle RDS instance prod-leftover-db (db.m5.large)",
            "RDS instance had 0 connections over 7 days.",
            "rds", "us-east-1", "prod-leftover-db",
            123.12, Confidence.MEDIUM,
            "aws rds stop-db-instance --region us-east-1 --db-instance-identifier prod-leftover-db",
            False, {"instance_class": "db.m5.large", "engine": "postgres", "max_connections_7d": 0},
        ),
        _f(
            "ebs.unattached", "Unattached EBS volume vol-0abc1234 (500 GB, gp2)",
            "500 GB gp2 volume in available state.",
            "ec2", "us-east-1", "vol-0abc1234",
            50.00, Confidence.HIGH,
            "aws ec2 delete-volume --region us-east-1 --volume-id vol-0abc1234",
            True, {
                "size_gb": 500, "volume_type": "gp2", "availability_zone": "us-east-1a",
                "create_time": (now - timedelta(days=129)).isoformat(),
            },
        ),
        _f(
            "ebs.unattached", "Unattached EBS volume vol-0def5678 (100 GB, gp3)",
            "100 GB gp3 volume in available state.",
            "ec2", "us-west-2", "vol-0def5678",
            8.00, Confidence.HIGH,
            "aws ec2 delete-volume --region us-west-2 --volume-id vol-0def5678",
            True, {
                "size_gb": 100, "volume_type": "gp3",
                "create_time": (now - timedelta(days=21)).isoformat(),
            },
        ),
        _f(
            "ec2.stopped-billed-ebs",
            "EC2 'old-staging' stopped for 187d, still billing $42.00/mo for EBS",
            "Stopped EC2 with 2 EBS volumes (350 GB total) still billing.",
            "ec2", "us-east-1", "i-0abcdef123456",
            42.00, Confidence.HIGH,
            "aws ec2 terminate-instances --region us-east-1 --instance-ids i-0abcdef123456",
            True, {"instance_type": "m5.xlarge", "days_stopped": 187, "volume_ids": ["vol-1", "vol-2"]},
        ),
        _f(
            "lb.unused", "Unused application load balancer staging-old-alb",
            "ALB has no registered targets.",
            "elb", "us-east-1", "staging-old-alb",
            16.20, Confidence.HIGH,
            "aws elbv2 delete-load-balancer --region us-east-1 --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/staging-old-alb/x",
            False, {"lb_type": "application", "reason": "no registered targets"},
        ),
        _f(
            "ebs.gp2-to-gp3", "Migrate gp2 → gp3: vol-prod001 (1000 GB)",
            "gp3 is 20% cheaper at equal performance.",
            "ec2", "us-east-1", "vol-prod001",
            20.00, Confidence.HIGH,
            "aws ec2 modify-volume --region us-east-1 --volume-id vol-prod001 --volume-type gp3",
            False, {"size_gb": 1000, "iops": 3000},
        ),
        _f(
            "ebs.gp2-to-gp3", "Migrate gp2 → gp3: vol-prod002 (500 GB)",
            "gp3 is 20% cheaper at equal performance.",
            "ec2", "us-east-1", "vol-prod002",
            10.00, Confidence.HIGH,
            "aws ec2 modify-volume --region us-east-1 --volume-id vol-prod002 --volume-type gp3",
            False, {"size_gb": 500},
        ),
        _f(
            "eip.unused", "Unused Elastic IP 52.12.34.56",
            "Allocated EIP not associated. AWS bills $0.005/hour.",
            "ec2", "us-east-1", "eipalloc-aaaa",
            3.60, Confidence.HIGH,
            "aws ec2 release-address --region us-east-1 --allocation-id eipalloc-aaaa",
            False, {"public_ip": "52.12.34.56", "domain": "vpc"},
        ),
        _f(
            "eip.unused", "Unused Elastic IP 52.78.90.12",
            "Allocated EIP not associated.",
            "ec2", "eu-west-1", "eipalloc-bbbb",
            3.60, Confidence.HIGH,
            "aws ec2 release-address --region eu-west-1 --allocation-id eipalloc-bbbb",
            False, {"public_ip": "52.78.90.12"},
        ),
        _f(
            "ebs.snapshot-old",
            "Old EBS snapshot snap-deadbeef01 (412d old, 200 GB)",
            "Snapshot is 412 days old.",
            "ec2", "us-east-1", "snap-deadbeef01",
            10.00, Confidence.MEDIUM,
            "aws ec2 delete-snapshot --region us-east-1 --snapshot-id snap-deadbeef01",
            True, {"size_gb": 200, "age_days": 412},
        ),
        _f(
            "logs.no-retention",
            "Log group '/aws/lambda/old-cron' has no retention policy",
            "Log group grows indefinitely. Set retention to 30 days.",
            "logs", "us-east-1", "/aws/lambda/old-cron",
            4.50, Confidence.HIGH,
            "aws logs put-retention-policy --region us-east-1 --log-group-name '/aws/lambda/old-cron' --retention-in-days 30",
            False, {"stored_bytes": 161061273600, "stored_gb": 150.0},
        ),
        _f(
            "logs.no-retention",
            "Log group '/aws/ecs/legacy-cluster' has no retention policy",
            "Log group grows indefinitely.",
            "logs", "us-west-2", "/aws/ecs/legacy-cluster",
            7.20, Confidence.HIGH,
            "aws logs put-retention-policy --region us-west-2 --log-group-name '/aws/ecs/legacy-cluster' --retention-in-days 30",
            False, {"stored_bytes": 257698037760, "stored_gb": 240.0},
        ),
        _f(
            "ec2.idle", "Idle EC2 'analytics-box' (m5.2xlarge), max 1.8% CPU over 7d",
            "Running m5.2xlarge peaked at 1.8% CPU over 7 days.",
            "ec2", "us-east-1", "i-0idleanalytics01",
            276.48, Confidence.MEDIUM,
            "aws ec2 stop-instances --region us-east-1 --instance-ids i-0idleanalytics01",
            False, {"instance_type": "m5.2xlarge", "max_cpu_pct_7d": 1.8},
        ),
        _f(
            "redshift.idle", "Idle Redshift cluster bi-warehouse (2× dc2.large)",
            "Redshift cluster had 0 connections over 7 days.",
            "redshift", "us-east-1", "bi-warehouse",
            360.00, Confidence.MEDIUM,
            "aws redshift pause-cluster --region us-east-1 --cluster-identifier bi-warehouse",
            False, {"node_type": "dc2.large", "number_of_nodes": 2, "max_connections_7d": 0},
        ),
        _f(
            "elasticache.idle", "Idle ElastiCache cluster sessions-cache (1× cache.r5.large)",
            "Cache cluster peaked at 0.4% CPU over 7 days.",
            "elasticache", "us-west-2", "sessions-cache",
            155.52, Confidence.MEDIUM,
            "aws elasticache delete-cache-cluster --region us-west-2 --cache-cluster-id sessions-cache",
            True, {"node_type": "cache.r5.large", "num_nodes": 1, "engine": "redis", "max_cpu_pct_7d": 0.4},
        ),
        _f(
            "dynamodb.idle-provisioned",
            "Idle provisioned DynamoDB table 'events-archive' (200 RCU / 200 WCU)",
            "Provisioned table consumed ~0 capacity over 7 days.",
            "dynamodb", "us-east-1", "events-archive",
            112.32, Confidence.MEDIUM,
            "aws dynamodb update-table --region us-east-1 --table-name events-archive --billing-mode PAY_PER_REQUEST",
            False, {"billing_mode": "PROVISIONED", "read_capacity_units": 200, "write_capacity_units": 200, "consumed_units_7d": 12},
        ),
        _f(
            "rds.snapshot-old",
            "Old manual RDS snapshot prod-db-pre-migration (288d old, 400 GB)",
            "Manual DB snapshot is 288 days old and still billing.",
            "rds", "us-east-1", "prod-db-pre-migration",
            38.00, Confidence.MEDIUM,
            "aws rds delete-db-snapshot --region us-east-1 --db-snapshot-identifier prod-db-pre-migration",
            True, {"size_gb": 400, "age_days": 288, "engine": "postgres", "source_db": "prod-db"},
        ),
        _f(
            "s3.incomplete-multipart-upload",
            "37 incomplete multipart upload(s) in 'data-lake-staging' (~64.20 GB orphaned)",
            "Bucket has 37 multipart uploads older than 7 days that were never "
            "completed or aborted — the parts keep billing storage but aren't visible "
            "as objects.",
            "s3", "us-east-1", "data-lake-staging",
            1.48, Confidence.HIGH,
            "aws s3api put-bucket-lifecycle-configuration --region us-east-1 "
            "--bucket data-lake-staging --lifecycle-configuration '{...}'",
            False, {
                "bucket": "data-lake-staging", "stale_upload_count": 37,
                "orphaned_bytes": 68943966208, "orphaned_gb": 64.2, "min_age_days": 7,
            },
        ),
        _f(
            "opensearch.idle",
            "Idle OpenSearch domain 'logs-search-old' (2× r5.large.search)",
            "Domain served effectively no searches or indexing over the last 7 days.",
            "es", "us-east-1", "logs-search-old",
            267.84, Confidence.MEDIUM,
            "aws opensearch delete-domain --region us-east-1 --domain-name logs-search-old",
            True, {
                "instance_type": "r5.large.search", "instance_count": 2,
                "dedicated_master": False, "search_plus_indexing_7d": 0.0,
            },
        ),
        # --- FinOps recommendations -------------------------------------------
        _f(
            "ec2.rightsizing",
            "Rightsize EC2 'api-worker-3': m5.2xlarge → m5.large (saves ~$207.36/mo)",
            "Compute Optimizer flags this instance as over-provisioned; m5.large "
            "covers the real load.",
            "ec2", "us-east-1", "i-0rightsize0001",
            207.36, Confidence.MEDIUM,
            "aws ec2 stop-instances --region us-east-1 --instance-ids i-0rightsize0001 && "
            "aws ec2 modify-instance-attribute --region us-east-1 --instance-id i-0rightsize0001 --instance-type m5.large && "
            "aws ec2 start-instances --region us-east-1 --instance-ids i-0rightsize0001",
            False, {
                "current_instance_type": "m5.2xlarge", "recommended_instance_type": "m5.large",
                "finding": "OVER_PROVISIONED", "performance_risk": 1.0,
                "estimated_monthly_savings_usd": 207.36, "source": "compute-optimizer",
            },
            category=Category.RIGHTSIZING,
        ),
        _f(
            "ce.savings-plan",
            "Buy a Compute Savings Plan (~$3.20/hr commit) — saves ~$842.00/mo",
            "Cost Explorer projects ~28% savings on steady compute usage from a "
            "1-year no-upfront Compute Savings Plan.",
            "compute", "global", "COMPUTE_SP",
            842.00, Confidence.MEDIUM,
            "# Review, then purchase in the console: "
            "https://console.aws.amazon.com/cost-management/home#/savings-plans/recommendations",
            False, {
                "plan_type": "COMPUTE_SP", "hourly_commitment_usd": "3.20",
                "estimated_savings_percentage": 28, "term": "1yr",
                "payment_option": "NO_UPFRONT", "source": "cost-explorer",
            },
            category=Category.COMMITMENT,
        ),
        _f(
            "ce.ri-recommendation",
            "Buy 4× RDS Reserved Instance (db.r5.large) — saves ~$318.00/mo",
            "Cost Explorer recommends 1-year no-upfront RDS RIs based on the last "
            "30 days of steady on-demand usage.",
            "rds", "us-east-1", "ri-rds-db.r5.large",
            318.00, Confidence.MEDIUM,
            "# Review, then purchase in the console: "
            "https://console.aws.amazon.com/cost-management/home#/ri/recommendations",
            False, {
                "service": "RDS", "instance_type": "db.r5.large", "recommended_count": 4,
                "term": "1yr", "payment_option": "NO_UPFRONT", "source": "cost-explorer",
            },
            category=Category.COMMITMENT,
        ),
        _f(
            "ce.anomaly",
            "Cost anomaly: AmazonS3 +$1,240.00 (2026-05-31)",
            "AWS Cost Anomaly Detection flagged unexpected S3 spend ~$1,240 above "
            "forecast — likely a runaway export job. One-off impact, not a saving.",
            "amazons3", "global", "anomaly-0001",
            0.00, Confidence.HIGH,
            "# Investigate in the console: "
            "https://console.aws.amazon.com/cost-management/home#/anomaly-detection/monitors",
            False, {
                "impact_usd": 1240.00, "impact_percentage": 380,
                "expected_spend_usd": 326.0, "actual_spend_usd": 1566.0,
                "anomaly_start": "2026-05-31", "root_cause_service": "AmazonS3",
                "source": "cost-anomaly-detection",
            },
            category=Category.ANOMALY,
        ),
        # --- Networking -------------------------------------------------------
        _f(
            "vpc.endpoint-idle", "Idle interface endpoint vpce-0staging01 (ecr.dkr, 3 AZ)",
            "This PrivateLink endpoint for com.amazonaws.us-east-1.ecr.dkr processed no "
            "traffic over 7 days but bills ~$21.60/mo ($7.20 per AZ).",
            "vpc", "us-east-1", "vpce-0staging01", 21.60, Confidence.MEDIUM,
            "aws ec2 delete-vpc-endpoints --region us-east-1 --vpc-endpoint-ids vpce-0staging01",
            False, {
                "vpc_id": "vpc-0staging", "service_name": "com.amazonaws.us-east-1.ecr.dkr",
                "availability_zones": 3, "bytes_processed": 0, "metrics_found": True,
                "private_dns_enabled": True,
            },
        ),
        _f(
            "vpc.abandoned", "VPC 'staging-2024' looks abandoned — ~$73.80/mo in leftover "
            "infrastructure",
            "No workload runs in vpc-0staging (no instances, Lambda functions, databases or "
            "containers), and its 4 billable resources (application-load-balancer, "
            "interface-endpoint, nat-gateway, public-ipv4) moved almost no traffic over 7 "
            "days. CloudTrail shows no activity on it in that time. Tearing it down removes "
            "the whole bill for this VPC.",
            "vpc", "us-east-1", "vpc-0staging", 73.80, Confidence.MEDIUM,
            "aws ec2 delete-vpc-endpoints --region us-east-1 --vpc-endpoint-ids vpce-0staging01\n"
            "aws elbv2 delete-load-balancer --region us-east-1 --load-balancer-arn "
            "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/staging-old-alb/x\n"
            "aws ec2 delete-nat-gateway --region us-east-1 --nat-gateway-id nat-0a1b2c3d4e5f6\n"
            "# finally: aws ec2 delete-vpc --region us-east-1 --vpc-id vpc-0staging",
            True, {
                "vpc_name": "staging-2024", "cidr": "10.20.0.0/16",
                "members": [
                    {"type": "nat-gateway", "id": "nat-0a1b2c3d4e5f6", "monthly_usd": 32.40},
                    {"type": "application-load-balancer", "id": "staging-old-alb",
                     "monthly_usd": 16.20},
                    {"type": "interface-endpoint", "id": "vpce-0staging01", "monthly_usd": 21.60},
                    {"type": "public-ipv4", "id": "54.10.20.30", "monthly_usd": 3.60},
                ],
                "member_resource_ids": ["nat-0a1b2c3d4e5f6", "staging-old-alb",
                                        "vpce-0staging01", "54.10.20.30"],
                "traffic_bytes": 0, "network_interfaces_in_use": 5,
                "last_cloudtrail_event": None, "active_peering_connections": [],
                "tgw_attachments": [], "flow_logs_enabled": False,
            },
        ),
        _f(
            "sg.unused", "Unused security group 'old-bastion' (sg-0bastion) — open to the "
            "internet on tcp/22",
            "Not attached to any network interface and not referenced by another group. It "
            "costs nothing, but unused groups get reattached by mistake — and this one allows "
            "inbound traffic from anywhere.",
            "ec2", "us-east-1", "sg-0bastion", 0.0, Confidence.MEDIUM,
            "aws ec2 delete-security-group --region us-east-1 --group-id sg-0bastion",
            False, {
                "vpc_id": "vpc-0prod", "group_name": "old-bastion", "inbound_rules": 1,
                "outbound_rules": 1, "open_to_world": ["tcp/22"],
            },
            category=Category.HYGIENE,
        ),
    ]

    return ScanResult(
        scan_id=str(uuid.uuid4()),
        account_id="123456789012",
        started_at=now - timedelta(seconds=12),
        finished_at=now,
        # A demo account opted in to every region; findings just happen to sit
        # in three of them.
        regions_scanned=commercial_regions(),
        findings=attach_guidance(
            roll_up_vpcs(mark_overlaps(sorted(findings, key=lambda f: -f.monthly_savings_usd)))
        ),
        is_demo=True,
        spend=DEMO_SPEND,
    )
