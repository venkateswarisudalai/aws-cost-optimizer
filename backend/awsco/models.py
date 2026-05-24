"""Core data models for findings and scans."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    HIGH = "high"      # >= $20/mo
    MEDIUM = "medium"  # $5–$20/mo
    LOW = "low"        # < $5/mo

    @classmethod
    def from_monthly_usd(cls, usd: float) -> Severity:
        if usd >= 20:
            return cls.HIGH
        if usd >= 5:
            return cls.MEDIUM
        return cls.LOW


class Confidence(str, Enum):
    HIGH = "high"      # signal is unambiguous (e.g., volume is detached)
    MEDIUM = "medium"  # signal is strong but not conclusive (e.g., 7d idle)
    LOW = "low"        # heuristic with notable false-positive risk


class Finding(BaseModel):
    id: str = Field(description="Stable hash of (check_id + resource_arn)")
    check_id: str = Field(description="e.g. 'ebs.unattached', 'nat.idle'")
    title: str
    description: str
    service: str = Field(description="ec2, rds, elb, logs, ...")
    region: str
    resource_arn: str
    resource_id: str = Field(description="Short display ID")
    monthly_savings_usd: float
    severity: Severity
    confidence: Confidence
    cli_fix_command: str
    fix_destructive: bool = Field(
        description="True if applying the fix deletes data (e.g., snapshot, volume)"
    )
    evidence: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def make_id(cls, check_id: str, resource_arn: str) -> str:
        return hashlib.sha256(f"{check_id}|{resource_arn}".encode()).hexdigest()[:16]


class ScanResult(BaseModel):
    scan_id: str
    account_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    regions_scanned: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    is_demo: bool = False

    @property
    def total_monthly_savings_usd(self) -> float:
        return sum(f.monthly_savings_usd for f in self.findings)

    @property
    def finding_count(self) -> int:
        return len(self.findings)
