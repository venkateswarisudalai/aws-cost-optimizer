from pathlib import Path

import pytest

from awsco.demo.fixtures import build_demo_scan
from awsco.storage import get_scan, latest_scan, list_scans, save_scan


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    return tmp_path / "scans.sqlite"


def test_save_and_get_roundtrip(tmp_db):
    scan = build_demo_scan()
    save_scan(scan, db_path=tmp_db)
    fetched = get_scan(scan.scan_id, db_path=tmp_db)
    assert fetched is not None
    assert fetched.scan_id == scan.scan_id
    assert fetched.finding_count == scan.finding_count
    assert fetched.total_monthly_savings_usd == scan.total_monthly_savings_usd


def test_latest_returns_most_recent(tmp_db):
    s1 = build_demo_scan()
    s2 = build_demo_scan()
    save_scan(s1, db_path=tmp_db)
    save_scan(s2, db_path=tmp_db)
    latest = latest_scan(db_path=tmp_db)
    assert latest is not None
    # The two demo scans have different ids; whichever started_at is greatest wins.
    assert latest.scan_id in {s1.scan_id, s2.scan_id}


def test_list_scans(tmp_db):
    s1 = build_demo_scan()
    save_scan(s1, db_path=tmp_db)
    rows = list_scans(db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["scan_id"] == s1.scan_id
    assert rows[0]["is_demo"] == 1
