"""Tests for the spend baseline, Cost Optimization Hub, new checks, overlap
de-duplication, and the account-ID guard. No AWS calls: `client()` is patched."""

from datetime import date, datetime, timedelta, timezone
from unittest import mock

import pytest

from awsco import scanner, spend
from awsco.collectors import cost_optimization_hub, ebs_io1_to_gp3, secretsmanager_unused
from awsco.models import Category, Confidence, Finding, Severity


def _paginating(payload):
    fake = mock.MagicMock()
    fake.get_paginator.return_value.paginate.return_value = [payload]
    return fake


def _finding(check_id, resource_id, savings, category=Category.WASTE, service="ec2"):
    return Finding(
        id=Finding.make_id(check_id, resource_id),
        check_id=check_id,
        title="t",
        description="d",
        service=service,
        region="us-east-1",
        resource_arn=resource_id,
        resource_id=resource_id,
        monthly_savings_usd=savings,
        category=category,
        severity=Severity.from_monthly_usd(savings),
        confidence=Confidence.HIGH,
        cli_fix_command="true",
        fix_destructive=False,
    )


# --- spend baseline ---------------------------------------------------------


def test_spend_summary_groups_by_service_across_periods():
    fake = mock.MagicMock()
    g = lambda name, amt: {"Keys": [name], "Metrics": {"UnblendedCost": {"Amount": str(amt)}}}
    fake.get_cost_and_usage.side_effect = [
        {"ResultsByTime": [
            {"Groups": [g("Amazon EC2", 100), g("Amazon RDS", 40)]},
            {"Groups": [g("Amazon EC2", 50)]},
        ]},
        {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": "80"}}}]},
    ]
    fake.get_cost_forecast.return_value = {"Total": {"Amount": "120"}}
    with mock.patch.object(spend, "client", return_value=fake):
        out = spend.spend_summary(today=date(2026, 9, 15))

    assert out["total_30d_usd"] == 190
    assert out["by_service"][0] == {"service": "Amazon EC2", "cost_usd": 150}
    assert out["month_to_date_usd"] == 80
    assert out["forecast_month_usd"] == 200


def test_spend_summary_returns_none_without_cost_explorer():
    from botocore.exceptions import ClientError

    fake = mock.MagicMock()
    fake.get_cost_and_usage.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "GetCostAndUsage"
    )
    with mock.patch.object(spend, "client", return_value=fake):
        assert spend.spend_summary() is None


# --- Cost Optimization Hub ---------------------------------------------------


def test_coh_maps_actions_to_categories():
    items = {"items": [
        {"recommendationId": "r1", "resourceId": "i-1", "currentResourceType": "Ec2Instance",
         "actionType": "MigrateToGraviton", "estimatedMonthlySavings": 42.5,
         "currentResourceSummary": "m5.xlarge", "recommendedResourceSummary": "m7g.xlarge",
         "region": "us-west-2", "restartNeeded": True, "rollbackPossible": True},
        {"recommendationId": "r2", "resourceId": "vol-1", "currentResourceType": "EbsVolume",
         "actionType": "Delete", "estimatedMonthlySavings": 8.0, "region": "us-east-1"},
        {"recommendationId": "r3", "resourceId": "sp", "currentResourceType": "ComputeSavingsPlans",
         "actionType": "PurchaseSavingsPlans", "estimatedMonthlySavings": 300.0},
        {"recommendationId": "r4", "resourceId": "tiny", "currentResourceType": "LambdaFunction",
         "actionType": "Rightsize", "estimatedMonthlySavings": 0.1},
    ]}
    with mock.patch.object(cost_optimization_hub, "client", return_value=_paginating(items)):
        found = {f.resource_id: f for f in cost_optimization_hub.collect("us-east-1", "1")}

    assert set(found) == {"i-1", "vol-1", "sp"}  # sub-$0.50 dropped
    assert found["i-1"].category == Category.RIGHTSIZING
    assert "m7g.xlarge" in found["i-1"].title
    assert found["vol-1"].category == Category.WASTE and found["vol-1"].fix_destructive
    assert found["sp"].category == Category.COMMITMENT and found["sp"].service == "compute"


# --- new regional checks ------------------------------------------------------


def test_io1_to_gp3_prices_the_delta_and_skips_high_iops():
    vols = {"Volumes": [
        {"VolumeId": "vol-a", "Size": 100, "Iops": 5000},
        {"VolumeId": "vol-b", "Size": 100, "Iops": 20000},
    ]}
    with mock.patch.object(ebs_io1_to_gp3, "client", return_value=_paginating(vols)):
        found = ebs_io1_to_gp3.collect("us-east-1", "1")

    assert [f.resource_id for f in found] == ["vol-a"]
    # io1: 100*0.125 + 5000*0.065 = 337.50; gp3: 100*0.08 + 2000*0.005 = 18.00
    assert found[0].monthly_savings_usd == 319.5
    assert "--volume-type gp3 --iops 5000" in found[0].cli_fix_command


def test_unused_secrets_uses_last_accessed_date():
    now = datetime.now(timezone.utc)
    secrets = {"SecretList": [
        {"Name": "old", "ARN": "arn:old", "LastAccessedDate": now - timedelta(days=200),
         "CreatedDate": now - timedelta(days=400)},
        {"Name": "hot", "ARN": "arn:hot", "LastAccessedDate": now - timedelta(days=1),
         "CreatedDate": now - timedelta(days=400)},
        {"Name": "new", "ARN": "arn:new", "CreatedDate": now - timedelta(days=5)},
        {"Name": "gone", "ARN": "arn:gone", "CreatedDate": now - timedelta(days=400),
         "DeletedDate": now},
    ]}
    with mock.patch.object(secretsmanager_unused, "client", return_value=_paginating(secrets)):
        found = secretsmanager_unused.collect("us-east-1", "1")

    assert [f.resource_id for f in found] == ["old"]
    assert "--recovery-window-in-days 7" in found[0].cli_fix_command


# --- overlap de-duplication --------------------------------------------------


def test_alternatives_for_same_resource_are_not_double_counted():
    idle = _finding("ec2.idle", "i-1", 100)
    resize = _finding("ec2.rightsizing", "i-1", 40, Category.RIGHTSIZING)
    coh = _finding("coh.recommendation", "i-1", 100, Category.RIGHTSIZING)
    other = _finding("ebs.unattached", "vol-1", 10)
    scanner.mark_overlaps([idle, resize, coh, other])

    assert idle.superseded_by is None  # tie with COH goes to our own check
    assert resize.superseded_by == idle.id and coh.superseded_by == idle.id
    assert other.superseded_by is None


def test_compute_commitments_are_one_pool():
    sp = _finding("ce.savings-plan", "Compute SP", 300, Category.COMMITMENT, "compute")
    ec2sp = _finding("ce.savings-plan", "EC2 SP", 350, Category.COMMITMENT, "compute")
    ri = _finding("ce.ri-recommendation", "3x m5", 200, Category.COMMITMENT, "ec2")
    rds = _finding("ce.ri-recommendation", "2x db.r5", 90, Category.COMMITMENT, "rds")
    scanner.mark_overlaps([sp, ec2sp, ri, rds])

    assert ec2sp.superseded_by is None and rds.superseded_by is None
    assert sp.superseded_by == ec2sp.id and ri.superseded_by == ec2sp.id


# --- account guard -------------------------------------------------------------


def test_scan_refuses_a_different_account():
    with mock.patch.object(scanner, "caller_identity", return_value={"account_id": "111111111111"}):
        with pytest.raises(scanner.AccountMismatchError, match="111111111111"):
            scanner.run_scan(regions=["us-east-1"], expected_account_id="222222222222")
