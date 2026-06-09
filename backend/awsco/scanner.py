"""Orchestrate all collectors across all regions concurrently."""

from __future__ import annotations

import contextvars
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from awsco import aws
from awsco.aws import InlineCredentials, caller_identity, enabled_regions
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
    credentials: InlineCredentials | None = None,
) -> ScanResult:
    started = datetime.now(timezone.utc)

    # Make pasted credentials ambient for the duration of this scan so the
    # collectors (which only know about `profile`) pick them up transparently.
    token = aws.set_inline_credentials(credentials) if credentials else None
    try:
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

        # Two kinds of collectors:
        #   - regional: one task per (region, collector) — idle/orphan finders.
        #   - global:   account-wide (Cost Explorer RI/Savings-Plans/anomaly
        #     recommendations). These hit the us-east-1 `ce` endpoint and would
        #     return identical results in every region, so we run them exactly
        #     once to avoid duplicate findings and wasted API calls.
        regional = [c for c in ALL_COLLECTORS if not getattr(c, "GLOBAL", False)]
        global_collectors = [c for c in ALL_COLLECTORS if getattr(c, "GLOBAL", False)]

        # Each task runs inside a copy of the current context so it inherits the
        # inline credentials set above.
        with ThreadPoolExecutor(max_workers=MAX_REGION_WORKERS) as pool:
            futures = [
                pool.submit(
                    contextvars.copy_context().run,
                    _run_collector, c, r, account_id, profile,
                )
                for r in regions
                for c in regional
            ]
            futures += [
                pool.submit(
                    contextvars.copy_context().run,
                    _run_collector, c, "us-east-1", account_id, profile,
                )
                for c in global_collectors
            ]
            for fut in as_completed(futures):
                f_list, err = fut.result()
                findings.extend(f_list)
                if err:
                    errors.append(err)
    finally:
        if token is not None:
            aws.reset_inline_credentials(token)

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
