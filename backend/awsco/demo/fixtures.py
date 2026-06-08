"""Realistic fake findings for the --demo-data mode."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from awsco.models import Confidence, Finding, ScanResult, Severity


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
        severity=Severity.from_monthly_usd(monthly),
        confidence=confidence,
        cli_fix_command=cli,
        fix_destructive=destructive,
        evidence=evidence,
    )


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
    ]

    return ScanResult(
        scan_id=str(uuid.uuid4()),
        account_id="123456789012",
        started_at=now - timedelta(seconds=12),
        finished_at=now,
        regions_scanned=["us-east-1", "us-west-2", "eu-west-1"],
        findings=sorted(findings, key=lambda f: -f.monthly_savings_usd),
        is_demo=True,
    )
