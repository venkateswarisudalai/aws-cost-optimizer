"""SQLite storage for scan history.

Schema is minimal: one row per scan with the full ScanResult serialized as JSON.
Findings can be re-derived from the JSON. Keeps backups portable and trivial.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from awsco.models import ScanResult

DEFAULT_DB_PATH = Path.home() / ".awsco" / "scans.sqlite"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scans (
            scan_id TEXT PRIMARY KEY,
            account_id TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            finding_count INTEGER NOT NULL,
            total_savings_usd REAL NOT NULL,
            is_demo INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scans_started ON scans (started_at DESC)"
    )
    conn.commit()
    return conn


def save_scan(scan: ScanResult, db_path: Path = DEFAULT_DB_PATH) -> None:
    conn = _connect(db_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO scans (
            scan_id, account_id, started_at, finished_at,
            finding_count, total_savings_usd, is_demo, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan.scan_id,
            scan.account_id,
            scan.started_at.isoformat(),
            scan.finished_at.isoformat() if scan.finished_at else None,
            scan.finding_count,
            scan.total_monthly_savings_usd,
            1 if scan.is_demo else 0,
            scan.model_dump_json(),
        ),
    )
    conn.commit()
    conn.close()


def get_scan(scan_id: str, db_path: Path = DEFAULT_DB_PATH) -> ScanResult | None:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT payload_json FROM scans WHERE scan_id = ?", (scan_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return ScanResult.model_validate(json.loads(row["payload_json"]))


def latest_scan(db_path: Path = DEFAULT_DB_PATH) -> ScanResult | None:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT payload_json FROM scans ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    return ScanResult.model_validate(json.loads(row["payload_json"]))


def list_scans(limit: int = 50, db_path: Path = DEFAULT_DB_PATH) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        """
        SELECT scan_id, account_id, started_at, finished_at,
               finding_count, total_savings_usd, is_demo
        FROM scans
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
