from awsco.demo.fixtures import build_demo_scan
from awsco.models import Severity


def test_demo_scan_has_findings():
    scan = build_demo_scan()
    assert scan.is_demo is True
    assert scan.finding_count >= 10
    assert scan.total_monthly_savings_usd > 100
    assert scan.account_id == "123456789012"


def test_demo_findings_sorted_desc():
    scan = build_demo_scan()
    savings = [f.monthly_savings_usd for f in scan.findings]
    assert savings == sorted(savings, reverse=True)


def test_demo_findings_have_cli_commands():
    scan = build_demo_scan()
    for f in scan.findings:
        assert f.cli_fix_command.startswith("aws ")
        assert f.region in f.cli_fix_command
        assert isinstance(f.severity, Severity)
