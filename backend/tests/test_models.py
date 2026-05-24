from awsco.models import Confidence, Finding, ScanResult, Severity


def test_severity_buckets():
    assert Severity.from_monthly_usd(0.5) == Severity.LOW
    assert Severity.from_monthly_usd(5) == Severity.MEDIUM
    assert Severity.from_monthly_usd(19.99) == Severity.MEDIUM
    assert Severity.from_monthly_usd(20) == Severity.HIGH
    assert Severity.from_monthly_usd(1000) == Severity.HIGH


def test_finding_id_stable():
    arn = "arn:aws:ec2:us-east-1:111:volume/vol-abc"
    a = Finding.make_id("ebs.unattached", arn)
    b = Finding.make_id("ebs.unattached", arn)
    assert a == b
    c = Finding.make_id("ebs.unattached", arn + "-different")
    assert a != c


def test_scanresult_totals():
    f1 = Finding(
        id="1", check_id="ebs.unattached", title="t", description="d",
        service="ec2", region="us-east-1",
        resource_arn="arn:aws:ec2:us-east-1:1:volume/vol-1", resource_id="vol-1",
        monthly_savings_usd=10.0, severity=Severity.MEDIUM, confidence=Confidence.HIGH,
        cli_fix_command="aws ec2 delete-volume --volume-id vol-1", fix_destructive=True,
    )
    f2 = Finding(
        id="2", check_id="nat.idle", title="t", description="d",
        service="ec2", region="us-east-1",
        resource_arn="arn:aws:ec2:us-east-1:1:natgateway/nat-1", resource_id="nat-1",
        monthly_savings_usd=32.40, severity=Severity.HIGH, confidence=Confidence.HIGH,
        cli_fix_command="aws ec2 delete-nat-gateway --nat-gateway-id nat-1",
        fix_destructive=False,
    )
    from datetime import datetime, timezone
    scan = ScanResult(
        scan_id="s", started_at=datetime.now(timezone.utc),
        regions_scanned=["us-east-1"], findings=[f1, f2],
    )
    assert scan.finding_count == 2
    assert scan.total_monthly_savings_usd == 42.40
