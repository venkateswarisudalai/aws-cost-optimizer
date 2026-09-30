"""Regression tests for the code-review findings on the cost-guidance branch."""

import json
from unittest import mock

from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi.testclient import TestClient

from awsco import scanner, slack
from awsco.collectors import s3_incomplete_multipart
from awsco.guidance import RiskLevel, guidance_for
from awsco.models import Category, Confidence, Finding, Severity
from awsco.server import AppState, create_app


def _f(check_id, resource_id, savings, region="us-east-1", category=Category.WASTE,
       service="ec2", evidence=None):
    return Finding(
        id=Finding.make_id(check_id, f"{region}/{resource_id}"),
        check_id=check_id, title="t", description="d", service=service, region=region,
        resource_arn=f"arn:{region}:{resource_id}", resource_id=resource_id,
        monthly_savings_usd=savings, category=category,
        severity=Severity.from_monthly_usd(savings), confidence=Confidence.HIGH,
        cli_fix_command="true", fix_destructive=False, evidence=evidence or {},
    )


# 1. Same name in two regions = two resources.
def test_same_name_in_two_regions_is_not_an_alternative():
    east = _f("dynamodb.idle-provisioned", "users", 50, "us-east-1")
    west = _f("dynamodb.idle-provisioned", "users", 40, "eu-west-1")
    scanner.mark_overlaps([east, west])
    assert east.superseded_by is None and west.superseded_by is None


# 2. Separate RI recommendations add up; SP vs EC2 RIs compares totals.
def test_separate_rds_ris_add_up():
    a = _f("ce.ri-recommendation", "3x db.r5.large", 200, category=Category.COMMITMENT, service="rds")
    b = _f("ce.ri-recommendation", "2x db.m5.xlarge", 150, category=Category.COMMITMENT, service="rds")
    scanner.mark_overlaps([a, b])
    assert a.superseded_by is None and b.superseded_by is None


def test_ec2_ris_that_beat_the_plan_win_as_a_group():
    plan = _f("ce.savings-plan", "Compute SP", 300, "global", Category.COMMITMENT, "compute")
    ri1 = _f("ce.ri-recommendation", "4x m5.large", 200, category=Category.COMMITMENT)
    ri2 = _f("ce.ri-recommendation", "2x c5.xlarge", 150, category=Category.COMMITMENT)
    scanner.mark_overlaps([plan, ri1, ri2])
    assert ri1.superseded_by is None and ri2.superseded_by is None  # 350 > 300
    assert plan.superseded_by == ri1.id


# 3. The VPC roll-up stays inside the VPC's region.
def test_vpc_rollup_ignores_same_named_lb_in_another_region():
    vpc = _f("vpc.abandoned", "vpc-1", 50, "us-east-1",
             evidence={"member_resource_ids": ["api"]})
    lb_here = _f("lb.unused", "api", 16.2, "us-east-1")
    lb_there = _f("lb.unused", "api", 16.2, "eu-west-1")
    scanner.roll_up_vpcs([vpc, lb_here, lb_there])
    assert lb_here.superseded_by == vpc.id
    assert lb_there.superseded_by is None


# 4. Demo sync never rewrites a real Slack ask.
def test_demo_sync_leaves_real_asks_alone(tmp_path, monkeypatch):
    import awsco.storage as storage

    db = tmp_path / "t.sqlite"
    for fn in ("save_scan", "latest_scan", "save_confirmation", "list_confirmations"):
        orig = getattr(storage, fn)
        monkeypatch.setattr(f"awsco.server.{fn}", lambda *a, _o=orig, **k: _o(*a, db_path=db, **k))
    storage.save_confirmation({"finding_id": "real", "channel": "C123", "message_ts": "1.1",
                               "status": "pending", "asked_at": "2026-09-01"}, db_path=db)
    storage.save_confirmation({"finding_id": "rehearsal", "channel": "demo",
                               "status": "pending", "asked_at": "2026-09-02"}, db_path=db)
    AppState.demo_mode = True
    rows = {r["finding_id"]: r for r in
            TestClient(create_app()).post("/confirmations/sync").json()["confirmations"]}
    assert rows["real"]["status"] == "pending"
    assert rows["rehearsal"]["status"] == "delete_ok"


# 5. The S3 lifecycle fix is only "safe" when there are no rules to overwrite.
def _s3_scan(lifecycle):
    s3 = mock.MagicMock()
    s3.list_buckets.return_value = {"Buckets": [{"Name": "b"}]}
    s3.get_bucket_location.return_value = {"LocationConstraint": None}
    s3.get_bucket_lifecycle_configuration.side_effect = lifecycle
    with mock.patch.object(s3_incomplete_multipart, "client", return_value=s3), \
         mock.patch.object(s3_incomplete_multipart, "_stale_upload_bytes",
                           return_value=(500 * 1024 ** 3, 3, False)):
        return s3_incomplete_multipart.collect("us-east-1", "1")[0]


def test_s3_fix_merges_when_bucket_has_rules():
    f = _s3_scan(lambda **_: {"Rules": [{"ID": "expire"}]})
    assert f.fix_destructive and "get-bucket-lifecycle-configuration" in f.cli_fix_command
    assert "file://lifecycle.json" in f.cli_fix_command
    assert guidance_for(f).risk_level == RiskLevel.DESTRUCTIVE


def test_s3_fix_is_safe_on_a_bucket_without_rules():
    err = ClientError({"Error": {"Code": "NoSuchLifecycleConfiguration"}}, "Get")
    f = _s3_scan(err)
    assert not f.fix_destructive and guidance_for(f).risk_level == RiskLevel.SAFE


# 6. A network error in the extras doesn't throw away the findings.
def test_spend_network_error_keeps_the_scan():
    found = _f("ebs.unattached", "vol-1", 10)
    collector = mock.MagicMock(CHECK_ID="ebs.unattached", GLOBAL=False)
    collector.collect.return_value = [found]
    with mock.patch.object(scanner, "caller_identity", return_value={"account_id": "1"}), \
         mock.patch.object(scanner, "ALL_COLLECTORS", [collector]), \
         mock.patch.object(scanner, "spend_summary",
                           side_effect=EndpointConnectionError(endpoint_url="https://ce")), \
         mock.patch.object(scanner.ownership, "resolve_owners",
                           side_effect=EndpointConnectionError(endpoint_url="https://ct")):
        result = scanner.run_scan(regions=["us-east-1"])
    assert [f.resource_id for f in result.findings] == ["vol-1"]
    assert result.spend is None
    assert {e["collector"] for e in result.errors} == {"spend", "ownership"}


# 8. Tag values can't inject Slack mentions or links.
def test_slack_escapes_aws_sourced_text():
    f = _f("ebs.unattached", "vol-<x>", 10)
    f.title = "Volume <!channel> & <https://evil|click>"
    f.owner = {"source": "tag", "name": "<!channel>", "tag_key": "owner"}
    blob = json.dumps(slack.build_message(f, None))
    assert "<!channel>" not in blob and "<https://evil" not in blob
    assert "&lt;!channel&gt;" in blob and "&amp;" in blob


# 10. The host allowlist has no unreachable IPv6 entry.
def test_allowed_hosts_are_ipv4_loopback():
    from awsco.server import _allowed_hosts

    assert "[::1]" not in _allowed_hosts()
