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


def _is_savings_plan(f: Finding) -> bool:
    return f.check_id == "ce.savings-plan" or (
        f.check_id == "coh.recommendation"
        and (f.evidence or {}).get("action_type") == "PurchaseSavingsPlans"
    )


def _is_ec2_ri(f: Finding) -> bool:
    return f.category == Category.COMMITMENT and f.service == "ec2" and not _is_savings_plan(f)


def _by_savings(f: Finding):
    # Biggest saving first; ties go to our own checks (concrete fix command)
    # over Cost Optimization Hub.
    return (-f.monthly_savings_usd, f.check_id == "coh.recommendation")


def _mark_alternatives(group: list[Finding]) -> None:
    group.sort(key=_by_savings)
    for other in group[1:]:
        other.superseded_by = group[0].id


def mark_overlaps(findings: list[Finding]) -> list[Finding]:
    """Flag findings that are alternatives to a bigger one, so totals are real.

    - Same resource (same region + id), e.g. an idle instance also flagged for
      rightsizing: stopping saves the full cost, resizing the delta — you do
      one, not both. Names are only unique per region, so region is part of
      the key: a table called 'users' in two regions is two resources.
    - Savings Plans: Compute SP and EC2 Instance SP recommendations are
      alternative ways to cover the same usage; only the biggest counts.
    - EC2 Reserved Instances vs Savings Plans: both discount the same EC2
      hours. Separate RI recommendations (different instance types / regions)
      add up, so the RI *total* is compared with the best Savings Plan and the
      smaller side is marked as the alternative.
    - Other RIs (RDS, ElastiCache, ...) are independent purchases and add up.
    """
    by_resource: dict[str, list[Finding]] = {}
    plans: list[Finding] = []
    ec2_ris: list[Finding] = []
    for f in findings:
        if f.category == Category.COMMITMENT:
            if _is_savings_plan(f):
                plans.append(f)
            elif _is_ec2_ri(f):
                ec2_ris.append(f)
            continue
        if f.category == Category.ANOMALY:
            continue  # one-off impacts, never alternatives
        by_resource.setdefault(f"{f.region}|{f.resource_id}", []).append(f)

    for group in by_resource.values():
        if len(group) > 1:
            _mark_alternatives(group)

    if len(plans) > 1:
        _mark_alternatives(plans)
    best_plan = min(plans, key=_by_savings) if plans else None
    ri_total = sum(f.monthly_savings_usd for f in ec2_ris)
    if best_plan and ec2_ris:
        if best_plan.monthly_savings_usd >= ri_total:
            for ri in ec2_ris:
                ri.superseded_by = best_plan.id
        else:
            top_ri = min(ec2_ris, key=_by_savings)
            for plan in plans:
                plan.superseded_by = top_ri.id
    return findings


def roll_up_vpcs(findings: list[Finding]) -> list[Finding]:
    """Per-resource findings inside an abandoned VPC (its NAT, load balancers,
    endpoints...) become parts of that VPC finding, so the VPC's total isn't
    added on top of theirs."""
    for vpc in (f for f in findings if f.check_id == "vpc.abandoned"):
        members = set(vpc.evidence.get("member_resource_ids", []))
        for f in findings:
            # Load balancer names repeat across regions: only this VPC's region.
            if f is vpc or f.region != vpc.region:
                continue
            if f.resource_id in members or f.resource_arn in members:
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

        # Extras run after every collector has finished; a network error here
        # must cost only the extra, never the findings already collected.
        try:
            spend = spend_summary(profile=profile)
        except Exception as exc:  # noqa: BLE001 — optional enrichment
            log.warning("Spend baseline failed: %s", exc)
            spend = None
            errors.append({"collector": "spend", "region": "us-east-1", "error": str(exc)})
        if resolve_owners:
            # Tags first, then CloudTrail (capped, paced): who to ask on Slack.
            try:
                ownership.resolve_owners(findings, profile=profile)
            except Exception as exc:  # noqa: BLE001 — optional enrichment
                log.warning("Owner lookup failed: %s", exc)
                errors.append({"collector": "ownership", "region": "-", "error": str(exc)})
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
