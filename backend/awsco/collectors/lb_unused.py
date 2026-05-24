"""Detect ALB/NLB with no registered targets, OR with zero requests over 7 days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import LB_MONTHLY

CHECK_ID = "lb.unused"
LOOKBACK_DAYS = 7


def _request_count(cw, lb_dim_value: str, namespace: str, metric: str) -> float:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric,
        Dimensions=[{"Name": "LoadBalancer", "Value": lb_dim_value}],
        StartTime=start,
        EndTime=end,
        Period=86400,
        Statistics=["Sum"],
    )
    return sum(p["Sum"] for p in resp.get("Datapoints", []))


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    elbv2 = client("elbv2", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        lbs = elbv2.describe_load_balancers().get("LoadBalancers", [])
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    for lb in lbs:
        lb_arn = lb["LoadBalancerArn"]
        lb_name = lb["LoadBalancerName"]
        lb_type = lb["Type"]  # 'application' | 'network' | 'gateway'

        # Try targets first — cheap
        targets_attached = False
        try:
            tgs = elbv2.describe_target_groups(LoadBalancerArn=lb_arn).get(
                "TargetGroups", []
            )
            for tg in tgs:
                health = elbv2.describe_target_health(
                    TargetGroupArn=tg["TargetGroupArn"]
                ).get("TargetHealthDescriptions", [])
                if health:
                    targets_attached = True
                    break
        except ClientError:
            pass

        reason = None
        if not targets_attached:
            reason = "no registered targets"
            req_count = 0.0
        else:
            # CloudWatch dimension format: "app/<name>/<id>" or "net/<name>/<id>"
            dim = "/".join(lb_arn.split(":loadbalancer/")[-1].split("/"))
            if lb_type == "application":
                req_count = _request_count(
                    cw, dim, "AWS/ApplicationELB", "RequestCount"
                )
            elif lb_type == "network":
                req_count = _request_count(
                    cw, dim, "AWS/NetworkELB", "ActiveFlowCount"
                )
            else:
                continue
            if req_count > 0:
                continue
            reason = f"0 requests over last {LOOKBACK_DAYS} days"

        findings.append(
            Finding(
                id=Finding.make_id(CHECK_ID, lb_arn),
                check_id=CHECK_ID,
                title=f"Unused {lb_type} load balancer {lb_name}",
                description=(
                    f"Load balancer {lb_name} has {reason}. "
                    f"Idle load balancers bill ~${LB_MONTHLY:.2f}/mo each."
                ),
                service="elb",
                region=region,
                resource_arn=lb_arn,
                resource_id=lb_name,
                monthly_savings_usd=round(LB_MONTHLY, 2),
                severity=Severity.from_monthly_usd(LB_MONTHLY),
                confidence=Confidence.HIGH if not targets_attached else Confidence.MEDIUM,
                cli_fix_command=(
                    f"aws elbv2 delete-load-balancer --region {region} "
                    f"--load-balancer-arn {lb_arn}"
                ),
                fix_destructive=False,
                evidence={
                    "lb_type": lb_type,
                    "reason": reason,
                    "scheme": lb.get("Scheme"),
                    "vpc_id": lb.get("VpcId"),
                    "created_time": lb["CreatedTime"].isoformat(),
                },
            )
        )

    return findings
