"""Detect Secrets Manager secrets nobody has read in 90+ days.

Every secret costs $0.40/month whether or not anything reads it. Secrets Manager
records LastAccessedDate (day granularity), so a secret with no access in 90
days — typically left behind by a decommissioned service — is safe to schedule
for deletion. Deletion has a 7–30 day recovery window, so it's reversible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from awsco.aws import client
from awsco.models import Confidence, Finding, Severity
from awsco.pricing import SECRETS_MANAGER_SECRET_MONTH

CHECK_ID = "secretsmanager.unused"
UNUSED_DAYS = 90


def collect(region: str, account_id: str, profile: str | None = None) -> list[Finding]:
    sm = client("secretsmanager", region, profile)
    findings: list[Finding] = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=UNUSED_DAYS)

    try:
        for page in sm.get_paginator("list_secrets").paginate():
            for secret in page.get("SecretList", []):
                if secret.get("DeletedDate"):
                    continue  # already scheduled for deletion
                created = secret.get("CreatedDate")
                last = secret.get("LastAccessedDate")
                # Never-read secrets only count once they're old enough to judge.
                reference = last or created
                if reference is None or reference > cutoff:
                    continue

                name = secret["Name"]
                arn = secret["ARN"]
                monthly = SECRETS_MANAGER_SECRET_MONTH
                idle_for = (now - reference).days
                findings.append(
                    Finding(
                        id=Finding.make_id(CHECK_ID, arn),
                        check_id=CHECK_ID,
                        title=f"Secret '{name}' not accessed in {idle_for} days",
                        description=(
                            f"This secret was last read "
                            f"{'on ' + last.date().isoformat() if last else 'never'} "
                            f"and still costs ${monthly:.2f}/mo. Scheduling deletion keeps a "
                            "7-day recovery window; restore with `restore-secret` if needed."
                        ),
                        service="secretsmanager",
                        region=region,
                        resource_arn=arn,
                        resource_id=name,
                        monthly_savings_usd=monthly,
                        severity=Severity.from_monthly_usd(monthly),
                        confidence=Confidence.MEDIUM,
                        cli_fix_command=(
                            f"aws secretsmanager delete-secret --region {region} "
                            f"--secret-id '{arn}' --recovery-window-in-days 7"
                        ),
                        fix_destructive=True,
                        evidence={
                            "last_accessed": last.isoformat() if last else None,
                            "created": created.isoformat() if created else None,
                            "days_unused": idle_for,
                            "rotation_enabled": bool(secret.get("RotationEnabled")),
                        },
                    )
                )
    except ClientError as e:
        if e.response["Error"]["Code"] in {"AccessDeniedException", "AccessDenied"}:
            return []
        raise

    return findings
