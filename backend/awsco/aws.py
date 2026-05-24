"""AWS session and region helpers.

Uses the standard boto3 credential chain: env vars, ~/.aws/credentials,
instance profile, etc. We never read or write credential files ourselves.
"""

from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.config import Config

DEFAULT_BOTO_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "standard"},
    user_agent_extra="aws-cost-optimizer/0.1.0",
)


def session(profile: str | None = None, region: str | None = None) -> boto3.Session:
    return boto3.Session(profile_name=profile, region_name=region)


def client(service: str, region: str, profile: str | None = None):
    return session(profile=profile, region=region).client(
        service, config=DEFAULT_BOTO_CONFIG
    )


def caller_identity(profile: str | None = None) -> dict[str, str]:
    sts = session(profile=profile, region="us-east-1").client("sts", config=DEFAULT_BOTO_CONFIG)
    ident = sts.get_caller_identity()
    return {
        "account_id": ident["Account"],
        "arn": ident["Arn"],
        "user_id": ident["UserId"],
    }


@lru_cache(maxsize=4)
def enabled_regions(profile: str | None = None) -> list[str]:
    """Return list of regions enabled for this account."""
    ec2 = session(profile=profile, region="us-east-1").client(
        "ec2", config=DEFAULT_BOTO_CONFIG
    )
    resp = ec2.describe_regions(AllRegions=False)  # only opted-in
    return sorted(r["RegionName"] for r in resp["Regions"])
