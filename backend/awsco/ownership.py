"""Work out who owns a resource, so the right person can be asked about it.

Two sources, best first:
  1. Tags — an explicit Owner / CreatedBy / Team / Email tag on the resource.
  2. CloudTrail — the identity behind the event that created the resource
     (RunInstances, CreateVolume, AllocateAddress, ...), or failing that, the
     last identity that changed it.

CloudTrail's lookup API only covers the last 90 days, so older resources
without an owner tag come back as "unknown"; the Slack flow then asks the
team channel instead of one person.

Lookups are read-only (cloudtrail:LookupEvents) and rate-limited by AWS to
2 requests/second per region, so the scanner caps how many it does.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Category, Finding

log = logging.getLogger(__name__)

# Tag keys people use for ownership, most specific first (compared lowercased).
OWNER_TAG_KEYS = [
    "owner", "owner-email", "owneremail", "created-by", "createdby", "creator",
    "email", "contact", "team", "squad", "maintainer",
]

_CREATE_PREFIXES = ("Create", "Run", "Allocate", "Put", "Register", "Import", "Copy")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

MAX_LOOKUPS_PER_SCAN = 60
_MIN_INTERVAL_S = 0.55  # stay under 2 req/s per region

# Findings about a specific resource (not account-wide recommendations).
_SKIP_CATEGORIES = {Category.COMMITMENT, Category.ANOMALY}


def owner_from_tags(tags: dict[str, str] | None) -> dict[str, Any] | None:
    if not tags:
        return None
    lowered = {k.lower(): v for k, v in tags.items() if v}
    for key in OWNER_TAG_KEYS:
        if key in lowered:
            value = lowered[key].strip()
            email = _EMAIL.search(value)
            return {
                "source": "tag",
                "name": value,
                "email": email.group(0).lower() if email else None,
                "tag_key": key,
            }
    return None


def identity_from_event(cloudtrail_event: dict[str, Any]) -> dict[str, Any]:
    """Human-readable identity from one CloudTrail record.

    Handles IAM users, SSO / assumed-role sessions (whose session name is
    usually the person's email), root, and AWS services acting on their own.
    """
    ident = cloudtrail_event.get("userIdentity", {}) or {}
    kind = ident.get("type", "")
    arn = ident.get("arn", "")
    invoked_by = ident.get("invokedBy") or cloudtrail_event.get("sourceIPAddress", "")

    if kind == "Root":
        name = "root account"
    elif kind == "IAMUser":
        name = ident.get("userName") or arn.rsplit("/", 1)[-1]
    elif kind in {"AssumedRole", "FederatedUser"}:
        # arn:aws:sts::123:assumed-role/<role>/<session-name>
        parts = arn.split("/")
        session = parts[-1] if len(parts) >= 3 else ""
        role = parts[1] if len(parts) >= 3 else ""
        name = session or role or arn
        if role and session and not _EMAIL.search(session):
            name = f"{session} (role {role})"
    elif kind == "AWSService":
        name = f"AWS service {invoked_by or ident.get('invokedBy', '')}".strip()
    else:
        name = arn or kind or "unknown"

    email = _EMAIL.search(arn) or _EMAIL.search(ident.get("userName", "") or "")
    return {
        "name": name,
        "email": email.group(0).lower() if email else None,
        "principal_arn": arn or None,
        "identity_type": kind or None,
        "is_service": kind == "AWSService",
    }


def owner_from_cloudtrail(
    resource_id: str, region: str, profile: str | None = None
) -> dict[str, Any] | None:
    ct = client("cloudtrail", region, profile)
    start = datetime.now(timezone.utc) - timedelta(days=90)
    latest: dict[str, Any] | None = None
    try:
        paginator = ct.get_paginator("lookup_events")
        pages = paginator.paginate(
            LookupAttributes=[{"AttributeKey": "ResourceName", "AttributeValue": resource_id}],
            StartTime=start,
            PaginationConfig={"MaxItems": 150, "PageSize": 50},
        )
        # Events arrive newest first; the creation event is usually the oldest.
        creator = None
        for page in pages:
            for ev in page.get("Events", []):
                name = ev.get("EventName", "")
                if name.startswith(("Describe", "List", "Get", "Lookup")):
                    continue
                if latest is None:
                    latest = ev
                if name.startswith(_CREATE_PREFIXES):
                    creator = ev
        chosen = creator or latest
        if chosen is None:
            return None
        record = json.loads(chosen.get("CloudTrailEvent") or "{}")
        who = identity_from_event(record)
        return {
            "source": "cloudtrail",
            **who,
            "event_name": chosen.get("EventName"),
            "event_time": chosen["EventTime"].isoformat()
            if isinstance(chosen.get("EventTime"), datetime)
            else str(chosen.get("EventTime", "")),
            "relationship": "created" if creator is chosen else "last changed",
        }
    except ClientError as e:
        log.info("CloudTrail lookup for %s failed: %s", resource_id, e.response["Error"]["Code"])
        return None


def resolve_owners(findings: list[Finding], profile: str | None = None) -> None:
    """Attach `owner` to findings in place. Tags are free; CloudTrail lookups
    are capped and paced per region."""
    lookups = 0
    last_call: dict[str, float] = {}
    for f in findings:
        if f.category in _SKIP_CATEGORIES or f.region == "global" or f.owner:
            continue
        tagged = owner_from_tags((f.evidence or {}).get("tags"))
        if tagged:
            f.owner = tagged
            continue
        if lookups >= MAX_LOOKUPS_PER_SCAN:
            f.owner = {"source": "unknown", "note": "owner lookup limit reached for this scan"}
            continue
        wait = _MIN_INTERVAL_S - (time.monotonic() - last_call.get(f.region, 0.0))
        if wait > 0:
            time.sleep(wait)
        last_call[f.region] = time.monotonic()
        lookups += 1
        found = owner_from_cloudtrail(f.resource_id, f.region, profile)
        f.owner = found or {
            "source": "unknown",
            "note": "no owner tag, and no CloudTrail activity in the last 90 days",
        }
