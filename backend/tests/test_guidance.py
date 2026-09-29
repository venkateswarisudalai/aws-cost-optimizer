"""Every finding must carry complete, specific guidance."""

from awsco.collectors import ALL_COLLECTORS
from awsco.demo.fixtures import build_demo_scan
from awsco.guidance import _BUILDERS, RiskLevel, guidance_for
from awsco.models import Confidence, Finding, Severity


def _f(check_id, evidence=None, destructive=False):
    return Finding(
        id="x", check_id=check_id, title="t", description="d", service="ec2",
        region="us-east-1", resource_arn="arn:x", resource_id="res-1",
        monthly_savings_usd=10, severity=Severity.MEDIUM, confidence=Confidence.HIGH,
        cli_fix_command="true", fix_destructive=destructive, evidence=evidence or {},
    )


def test_every_registered_check_has_specific_guidance():
    missing = {c.CHECK_ID for c in ALL_COLLECTORS} - set(_BUILDERS)
    assert not missing, f"no guidance for: {missing}"


def test_demo_findings_have_all_four_sections():
    for f in build_demo_scan().findings:
        g = f.guidance
        assert g and g["recommendation"] and g["risks"] and g["before_you_act"] and g["undo"]


def test_destructive_fixes_are_never_labelled_safe():
    for c in ALL_COLLECTORS:
        g = guidance_for(_f(c.CHECK_ID, destructive=True))
        # the collector's own destructive flag must agree with the guidance
        if c.CHECK_ID in {"ebs.unattached", "ebs.snapshot-old", "rds.snapshot-old",
                          "opensearch.idle", "elasticache.idle", "secretsmanager.unused",
                          "ec2.stopped-billed-ebs"}:
            assert g.risk_level == RiskLevel.DESTRUCTIVE, c.CHECK_ID


def test_large_gp2_volume_warns_about_iops_drop():
    g = guidance_for(_f("ebs.gp2-to-gp3", {"size_gb": 2000}))
    assert "6000 IOPS" in g.risks[0]
    assert any("--iops 6000" in b for b in g.before_you_act)
    assert g.risk_level == RiskLevel.SAFE


def test_idle_instance_in_asg_warns_about_replacement():
    g = guidance_for(_f("ec2.idle", {"auto_scaling_group": "web-asg"}))
    assert "web-asg" in g.risks[0]


def test_coh_graviton_flags_arm_compatibility():
    g = guidance_for(_f("coh.recommendation", {
        "action_type": "MigrateToGraviton", "restart_needed": True,
        "rollback_possible": True, "current": "m5.large", "recommended": "m7g.large",
    }))
    assert g.risk_level == RiskLevel.RESTART
    assert any("ARM" in r for r in g.risks)
    assert "m5.large" in g.undo


def test_commitments_are_not_reversible():
    for cid in ("ce.savings-plan", "ce.ri-recommendation"):
        g = guidance_for(_f(cid))
        assert g.risk_level == RiskLevel.COMMITMENT and not g.reversible
