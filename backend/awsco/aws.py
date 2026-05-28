"""AWS session and region helpers.

Uses the standard boto3 credential chain: env vars, ~/.aws/credentials,
instance profile, etc. We never read or write credential files ourselves.

A scan may also supply *inline* credentials (access key / secret / session
token) that the user pasted into the dashboard. Those are held only for the
duration of the scan via a context variable and are never written to disk,
logged, or persisted in the scan history.
"""

from __future__ import annotations

import contextvars
from typing import TypedDict

import boto3
from botocore.config import Config

DEFAULT_BOTO_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "standard"},
    user_agent_extra="aws-cost-optimizer/0.1.0",
)


class InlineCredentials(TypedDict, total=False):
    access_key_id: str
    secret_access_key: str
    session_token: str | None


# Set by run_scan for the lifetime of a single scan; copied into each collector
# worker thread via contextvars.copy_context(). Default None == use the normal
# boto3 chain (profile / env / instance role).
_inline_credentials: contextvars.ContextVar[InlineCredentials | None] = (
    contextvars.ContextVar("awsco_inline_credentials", default=None)
)


def set_inline_credentials(creds: InlineCredentials | None):
    """Set ambient inline credentials. Returns a token for reset()."""
    return _inline_credentials.set(creds)


def reset_inline_credentials(token) -> None:
    _inline_credentials.reset(token)


def session(
    profile: str | None = None,
    region: str | None = None,
    credentials: InlineCredentials | None = None,
) -> boto3.Session:
    creds = credentials or _inline_credentials.get()
    if creds:
        return boto3.Session(
            aws_access_key_id=creds["access_key_id"],
            aws_secret_access_key=creds["secret_access_key"],
            aws_session_token=creds.get("session_token") or None,
            region_name=region,
        )
    return boto3.Session(profile_name=profile, region_name=region)


def client(
    service: str,
    region: str,
    profile: str | None = None,
    credentials: InlineCredentials | None = None,
):
    return session(profile=profile, region=region, credentials=credentials).client(
        service, config=DEFAULT_BOTO_CONFIG
    )


def caller_identity(
    profile: str | None = None,
    credentials: InlineCredentials | None = None,
) -> dict[str, str]:
    sts = session(
        profile=profile, region="us-east-1", credentials=credentials
    ).client("sts", config=DEFAULT_BOTO_CONFIG)
    ident = sts.get_caller_identity()
    return {
        "account_id": ident["Account"],
        "arn": ident["Arn"],
        "user_id": ident["UserId"],
    }


# OptInStatus values that mean the region is usable (and therefore scannable).
SCANNABLE_OPT_IN = {"opt-in-not-required", "opted-in"}


def account_regions(
    profile: str | None = None,
    credentials: InlineCredentials | None = None,
) -> list[dict[str, object]]:
    """Return every region in the account's partition with its opt-in status.

    Includes regions that aren't activated on this account (OptInStatus
    'not-opted-in'); those are marked enabled=False so the UI can show them
    but not scan them — calling APIs there would just raise OptInRequired.
    Note: GovCloud / China are separate partitions and won't appear here.
    """
    ec2 = session(
        profile=profile, region="us-east-1", credentials=credentials
    ).client("ec2", config=DEFAULT_BOTO_CONFIG)
    resp = ec2.describe_regions(AllRegions=True)
    out: list[dict[str, object]] = []
    for r in resp["Regions"]:
        status = r.get("OptInStatus", "")
        out.append(
            {
                "name": r["RegionName"],
                "opt_in_status": status,
                "enabled": status in SCANNABLE_OPT_IN,
            }
        )
    return sorted(out, key=lambda x: str(x["name"]))


def enabled_regions(
    profile: str | None = None,
    credentials: InlineCredentials | None = None,
) -> list[str]:
    """Region names that are activated for this account (scannable)."""
    return [
        str(r["name"])
        for r in account_regions(profile=profile, credentials=credentials)
        if r["enabled"]
    ]


def list_profiles() -> list[str]:
    """Return profile names from ~/.aws/credentials and ~/.aws/config."""
    return sorted(boto3.Session().available_profiles)
