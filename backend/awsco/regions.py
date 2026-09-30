"""The AWS commercial region catalog, for demo mode and tests.

Real scans never use this: they ask the account itself
(ec2:DescribeRegions AllRegions=True) so newly launched regions and the
account's own opt-in choices are always reflected.
"""

from __future__ import annotations

import boto3

# Regions every account has on by default. Everything launched since 2019 is
# opt-in: the account owner must enable it before any API call works there.
DEFAULT_ENABLED = {
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "sa-east-1",
    "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-north-1",
    "ap-south-1", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-southeast-1", "ap-southeast-2",
}


def commercial_regions() -> list[str]:
    """Every region in the standard `aws` partition that botocore knows about."""
    return sorted(boto3.Session().get_available_regions("ec2"))
