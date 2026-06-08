"""Detect DynamoDB tables on PROVISIONED billing with ~zero consumed capacity.

A provisioned table bills for its reserved RCU/WCU whether or not anyone reads
or writes. A table that has consumed effectively nothing for a week is paying
for capacity it doesn't use — switching it to on-demand (PAY_PER_REQUEST) drops
the idle cost to zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import dynamodb_provisioned_monthly_cost

CHECK_ID = "dynamodb.idle-provisioned"
LOOKBACK_DAYS = 7
CONSUMED_THRESHOLD = 100.0  # total consumed units over 7d below this == idle


def _consumed(cw, table: str, metric: str) -> float:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    resp = cw.get_metric_statistics(
        Namespace="AWS/DynamoDB",
        MetricName=metric,
        Dimensions=[{"Name": "TableName", "Value": table}],
        StartTime=start,
        EndTime=end,
        Period=86400,
        Statistics=["Sum"],
    )
    return sum(p["Sum"] for p in resp.get("Datapoints", []))


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    ddb = client("dynamodb", region, profile)
    cw = client("cloudwatch", region, profile)
    findings: list[Finding] = []

    try:
        paginator = ddb.get_paginator("list_tables")
        table_names = [
            name for page in paginator.paginate() for name in page["TableNames"]
        ]
    except ClientError as e:
        if e.response["Error"]["Code"] in {"UnauthorizedOperation", "AccessDenied"}:
            return []
        raise

    for name in table_names:
        try:
            table = ddb.describe_table(TableName=name)["Table"]
        except ClientError:
            continue

        # PAY_PER_REQUEST tables have no idle capacity cost — skip them.
        billing = (table.get("BillingModeSummary") or {}).get(
            "BillingMode", "PROVISIONED"
        )
        if billing != "PROVISIONED":
            continue

        throughput = table.get("ProvisionedThroughput") or {}
        rcu = throughput.get("ReadCapacityUnits", 0)
        wcu = throughput.get("WriteCapacityUnits", 0)
        if rcu == 0 and wcu == 0:
            continue  # on-demand-ish / nothing reserved

        try:
            consumed = _consumed(
                cw, name, "ConsumedReadCapacityUnits"
            ) + _consumed(cw, name, "ConsumedWriteCapacityUnits")
        except ClientError:
            continue
        if consumed > CONSUMED_THRESHOLD:
            continue

        monthly = dynamodb_provisioned_monthly_cost(rcu, wcu)
        arn = table.get(
            "TableArn", f"arn:aws:dynamodb:{region}:{account_id}:table/{name}"
        )

        findings.append(
            Finding(
                id=Finding.make_id(CHECK_ID, arn),
                check_id=CHECK_ID,
                title=(
                    f"Idle provisioned DynamoDB table '{name}' "
                    f"({rcu} RCU / {wcu} WCU)"
                ),
                description=(
                    f"Table '{name}' is on PROVISIONED billing but consumed only "
                    f"{int(consumed)} capacity units over the last {LOOKBACK_DAYS} days. "
                    "Switch it to on-demand (PAY_PER_REQUEST) so you pay per request "
                    "instead of for idle reserved capacity. (GSIs not counted, so real "
                    "savings may be higher.)"
                ),
                service="dynamodb",
                region=region,
                resource_arn=arn,
                resource_id=name,
                monthly_savings_usd=monthly,
                severity=Severity.from_monthly_usd(monthly),
                confidence=Confidence.MEDIUM,
                cli_fix_command=(
                    f"aws dynamodb update-table --region {region} --table-name {name} "
                    "--billing-mode PAY_PER_REQUEST"
                ),
                fix_destructive=False,
                evidence={
                    "billing_mode": billing,
                    "read_capacity_units": rcu,
                    "write_capacity_units": wcu,
                    "consumed_units_7d": int(consumed),
                    "item_count": table.get("ItemCount"),
                },
            )
        )

    return findings
