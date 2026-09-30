"""Recommendations from AWS Cost Optimization Hub.

Cost Optimization Hub is AWS's own production aggregator: it merges Compute
Optimizer rightsizing, idle-resource detection, Graviton migrations, and
Savings Plans / Reserved Instance purchases for EC2, EBS, Lambda, ECS/Fargate,
RDS, Aurora, ElastiCache, OpenSearch, Redshift, DynamoDB and more — and, unlike
summing each source yourself, it already de-duplicates overlapping savings for
the same resource (e.g. rightsize-then-commit is priced as one action).

We ask for the single best recommendation per resource
(includeAllRecommendations=False). The hub must be opted in once per account
(free); if it isn't, the API returns an error and we emit nothing.

Global, account-wide check (the hub's endpoint is us-east-1).
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Confidence, Finding, Severity

CHECK_ID = "coh.recommendation"
GLOBAL = True

CONSOLE_URL = "https://console.aws.amazon.com/costmanagement/home#/cost-optimization-hub"

_IGNORABLE = {
    "AccessDeniedException",
    "AccessDenied",
    "OptInRequiredException",
    "ValidationException",  # returned when the account isn't enrolled
    "ResourceNotFoundException",
}

# actionType -> (category, is the fix destructive?)
_ACTIONS = {
    "Delete": (Category.WASTE, True),
    "Stop": (Category.WASTE, False),
    "Rightsize": (Category.RIGHTSIZING, False),
    "ScaleIn": (Category.RIGHTSIZING, False),
    "MigrateToGraviton": (Category.RIGHTSIZING, False),
    "Upgrade": (Category.RIGHTSIZING, False),
    "PurchaseSavingsPlans": (Category.COMMITMENT, False),
    "PurchaseReservedInstances": (Category.COMMITMENT, False),
}

_ACTION_VERB = {
    "Delete": "Delete",
    "Stop": "Stop",
    "Rightsize": "Rightsize",
    "ScaleIn": "Scale in",
    "MigrateToGraviton": "Move to Graviton",
    "Upgrade": "Upgrade",
    "PurchaseSavingsPlans": "Buy Savings Plan for",
    "PurchaseReservedInstances": "Buy Reserved Instances for",
}

_SERVICE_BY_RESOURCE = {
    "Ec2Instance": "ec2",
    "Ec2AutoScalingGroup": "ec2",
    "EbsVolume": "ec2",
    "LambdaFunction": "lambda",
    "EcsService": "ecs",
    "RdsDbInstance": "rds",
    "RdsDbInstanceStorage": "rds",
    "AuroraDbClusterStorage": "rds",
    "DynamoDbReservedCapacity": "dynamodb",
    "ElastiCacheReservedInstances": "elasticache",
    "OpenSearchReservedInstances": "opensearch",
    "RedshiftReservedInstances": "redshift",
    "RdsReservedInstances": "rds",
    "Ec2ReservedInstances": "ec2",
    "ComputeSavingsPlans": "compute",
    "Ec2InstanceSavingsPlans": "compute",
    "SageMakerSavingsPlans": "sagemaker",
    "MemoryDbReservedInstances": "memorydb",
}


def _to_finding(rec: dict, account_id: str) -> Finding | None:
    monthly = round(float(rec.get("estimatedMonthlySavings") or 0.0), 2)
    if monthly < 0.5:
        return None

    action = rec.get("actionType", "")
    category, destructive = _ACTIONS.get(action, (Category.RIGHTSIZING, False))
    resource_type = rec.get("currentResourceType", "")
    resource_id = rec.get("resourceId") or rec.get("recommendationId", "unknown")
    arn = rec.get("resourceArn") or f"coh:{rec.get('recommendationId', resource_id)}"
    region = rec.get("region") or "global"
    current = rec.get("currentResourceSummary") or ""
    target = rec.get("recommendedResourceSummary") or ""
    verb = _ACTION_VERB.get(action, action or "Optimize")

    change = f": {current} → {target}" if current and target and current != target else ""
    title = f"{verb} {resource_type} {resource_id}{change} (saves ~${monthly:,.2f}/mo)"

    restart = rec.get("restartNeeded")
    rollback = rec.get("rollbackPossible")
    effort = rec.get("implementationEffort")
    caveats = []
    if restart:
        caveats.append("needs a restart")
    if rollback is False:
        caveats.append("can't be rolled back")
    if category == Category.COMMITMENT:
        caveats.append("is a 1–3 year financial commitment")
    caveat_text = f" This change {', '.join(caveats)}." if caveats else ""

    rec_account = rec.get("accountId") or account_id
    return Finding(
        id=Finding.make_id(CHECK_ID, arn),
        check_id=CHECK_ID,
        title=title,
        description=(
            f"AWS Cost Optimization Hub recommends '{action}' for this {resource_type}, "
            f"estimating ~${monthly:,.2f}/mo "
            f"({rec.get('estimatedSavingsPercentage', '?')}% of its cost).{caveat_text} "
            "Review the recommendation in the console before acting."
        ),
        service=_SERVICE_BY_RESOURCE.get(resource_type, resource_type.lower() or "aws"),
        region=region,
        resource_arn=arn,
        resource_id=resource_id,
        monthly_savings_usd=monthly,
        category=category,
        severity=Severity.from_monthly_usd(monthly),
        # AWS's own utilisation-backed estimate, but still needs human review.
        confidence=Confidence.MEDIUM,
        cli_fix_command=(
            f"aws cost-optimization-hub get-recommendation --region us-east-1 "
            f"--recommendation-id {rec.get('recommendationId', '')}  "
            f"# then apply in the console: {CONSOLE_URL}"
        ),
        fix_destructive=destructive,
        evidence={
            "action_type": action,
            "resource_type": resource_type,
            "current": current,
            "recommended": target,
            "estimated_savings_percentage": rec.get("estimatedSavingsPercentage"),
            "estimated_monthly_cost_usd": rec.get("estimatedMonthlyCost"),
            "implementation_effort": effort,
            "restart_needed": restart,
            "rollback_possible": rollback,
            "recommendation_account_id": rec_account,
            "recommendation_id": rec.get("recommendationId"),
            "last_refresh": str(rec.get("lastRefreshTimestamp") or ""),
            "source": "cost-optimization-hub",
        },
    )


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    hub = client("cost-optimization-hub", "us-east-1", profile)
    findings: list[Finding] = []
    try:
        paginator = hub.get_paginator("list_recommendations")
        for page in paginator.paginate(includeAllRecommendations=False):
            for rec in page.get("items", []):
                f = _to_finding(rec, account_id)
                if f is not None:
                    findings.append(f)
    except ClientError as e:
        if e.response["Error"]["Code"] in _IGNORABLE:
            return []
        raise
    return findings
