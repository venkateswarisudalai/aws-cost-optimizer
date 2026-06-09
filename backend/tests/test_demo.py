from awsco.demo.fixtures import build_demo_scan
from awsco.models import Category, Severity

# Categories whose "fix" is a real, region-scoped `aws` CLI command. Commitment
# (RI/Savings Plans) and anomaly findings point at a console review page instead
# — you don't shell-script a financial commitment or a spike investigation.
_CLI_FIXABLE = {Category.WASTE, Category.RIGHTSIZING}


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
        assert isinstance(f.severity, Severity)
        assert f.cli_fix_command  # always present
        if f.category in _CLI_FIXABLE:
            assert f.cli_fix_command.startswith("aws ")
            assert f.region in f.cli_fix_command


def test_demo_covers_all_categories():
    scan = build_demo_scan()
    present = {f.category for f in scan.findings}
    assert present == set(Category), f"missing categories: {set(Category) - present}"
