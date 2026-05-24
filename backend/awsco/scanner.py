"""Orchestrate all collectors across all regions concurrently."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from awsco.aws import caller_identity, enabled_regions
from awsco.collectors import ALL_COLLECTORS
from awsco.models import Finding, ScanResult

log = logging.getLogger(__name__)

# Most collectors are global-per-region; logs/elbv2/rds/ec2 all support every
# region. Bound concurrency to avoid throttling — 8 region workers × ~5 API
# calls per collector is well within default boto throttles.
MAX_REGION_WORKERS = 8


def _run_collector(collector, region: str, account_id: str, profile: str | None):
    try:
        return collector.collect(region, account_id, profile), None
    except Exception as exc:  # noqa: BLE001 — collector boundary
        log.warning(
            "Collector %s failed in %s: %s",
            collector.CHECK_ID, region, exc,
        )
        return [], {
            "collector": collector.CHECK_ID,
            "region": region,
            "error": str(exc),
        }


def run_scan(
    profile: str | None = None,
    regions: list[str] | None = None,
) -> ScanResult:
    started = datetime.now(timezone.utc)
    ident = caller_identity(profile=profile)
    account_id = ident["account_id"]

    if regions is None:
        try:
            regions = enabled_regions(profile=profile)
        except Exception as exc:
            log.error("Could not list regions, falling back to us-east-1: %s", exc)
            regions = ["us-east-1"]

    findings: list[Finding] = []
    errors: list[dict[str, str]] = []

    # One thread per (region, collector). For 9 collectors × ~16 regions that's
    # ~150 tasks — comfortably small for a thread pool.
    with ThreadPoolExecutor(max_workers=MAX_REGION_WORKERS) as pool:
        futures = [
            pool.submit(_run_collector, c, r, account_id, profile)
            for r in regions
            for c in ALL_COLLECTORS
        ]
        for fut in as_completed(futures):
            f_list, err = fut.result()
            findings.extend(f_list)
            if err:
                errors.append(err)

    finished = datetime.now(timezone.utc)
    return ScanResult(
        scan_id=str(uuid.uuid4()),
        account_id=account_id,
        started_at=started,
        finished_at=finished,
        regions_scanned=regions,
        findings=sorted(findings, key=lambda f: -f.monthly_savings_usd),
        errors=errors,
    )
