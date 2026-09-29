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
from awsco.guidance import attach_guidance
from awsco.models import Category, Finding, ScanResult
from awsco import ownership
from awsco.spend import spend_summary

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


class AccountMismatchError(ValueError):
    """The credentials belong to a different account than the user expected."""


# Commitments that draw on the same pool of usage are alternatives: a Compute
# Savings Plan, an EC2 Instance Savings Plan and EC2 RIs all discount the same
# EC2 hours, so buying all three doesn't triple the saving.
_COMPUTE_POOL = {"compute", "ec2", "lambda", "ecs", "fargate"}


def _overlap_key(f: Finding) -> str:
    if f.category == Category.COMMITMENT:
        pool = "compute" if f.service in _COMPUTE_POOL else f.service
        return f"commitment:{pool}"
    if f.category == Category.ANOMALY:
        return f"anomaly:{f.id}"  # never overlaps
    return f"resource:{f.resource_id}"


def mark_overlaps(findings: list[Finding]) -> list[Finding]:
    """Flag findings that are alternatives to a bigger one, so totals are real.

    E.g. an idle instance may also be flagged for rightsizing; stopping it
    saves the full cost, resizing saves the delta — you do one, not both. The
    biggest saving in each group is primary; ties go to our own collectors
    (they carry a concrete fix command) over Cost Optimization Hub.
    """
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        groups.setdefault(_overlap_key(f), []).append(f)
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda f: (-f.monthly_savings_usd, f.check_id == "coh.recommendation")
        )
        primary = group[0]
        for other in group[1:]:
            other.superseded_by = primary.id
    return findings


def roll_up_vpcs(findings: list[Finding]) -> list[Finding]:
    """Per-resource findings inside an abandoned VPC (its NAT, load balancers,
    endpoints...) become parts of that VPC finding, so the VPC's total isn't
    added on top of theirs."""
    for vpc in (f for f in findings if f.check_id == "vpc.abandoned"):
        members = set(vpc.evidence.get("member_resource_ids", []))
        for f in findings:
            if f is not vpc and (f.resource_id in members or f.resource_arn in members):
                f.superseded_by = vpc.id
    return findings


def run_scan(
    profile: str | None = None,
    regions: list[str] | None = None,
    credentials: InlineCredentials | None = None,
    expected_account_id: str | None = None,
    lookback_days: int | None = None,
    resolve_owners: bool = True,
) -> ScanResult:
    started = datetime.now(timezone.utc)

    # Make pasted credentials ambient for the duration of this scan so the
    # collectors (which only know about `profile`) pick them up transparently.
    token = aws.set_inline_credentials(credentials) if credentials else None
    lb_token = aws.set_lookback_days(lookback_days or aws.DEFAULT_LOOKBACK_DAYS)
    window = aws.lookback_days()
    try:
        ident = caller_identity(profile=profile)
        account_id = ident["account_id"]
        # Guard against scanning the wrong account with a stray profile/key.
        if expected_account_id and expected_account_id != account_id:
            raise AccountMismatchError(
                f"These credentials belong to account {account_id}, "
                f"not {expected_account_id}. Nothing was scanned."
            )

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

        spend = spend_summary(profile=profile)
        if resolve_owners:
            # Tags first, then CloudTrail (capped, paced): who to ask on Slack.
            ownership.resolve_owners(findings, profile=profile)
    finally:
        if token is not None:
            aws.reset_inline_credentials(token)
        aws.reset_lookback_days(lb_token)

    # Record the window on every finding so the UI can say "over 30d", not "7d".
    for f in findings:
        f.evidence.setdefault("lookback_days", window)

    finished = datetime.now(timezone.utc)
    return ScanResult(
        scan_id=str(uuid.uuid4()),
        account_id=account_id,
        started_at=started,
        finished_at=finished,
        regions_scanned=regions,
        findings=attach_guidance(roll_up_vpcs(mark_overlaps(sorted(findings, key=lambda f: -f.monthly_savings_usd)))),
        errors=errors,
        spend=spend,
        lookback_days=window,
    )
