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


class Category(str, Enum):
    """What kind of FinOps signal a finding represents.

    `waste` is the original idle/orphan-resource finding — a recurring charge
    you can stop. The FinOps additions extend the model:
      - `rightsizing` — a resource that's running but over-provisioned
        (Compute Optimizer). Savings is the delta, not the full cost.
      - `commitment` — buy a Reserved Instance / Savings Plan to discount
        steady-state on-demand usage (Cost Explorer recommendations).
      - `anomaly` — an unexpected spend spike (Cost Anomaly Detection). Not a
        recurring saving, so its `monthly_savings_usd` is 0 and the impact
        lives in `evidence`.
    """

    WASTE = "waste"
    RIGHTSIZING = "rightsizing"
    COMMITMENT = "commitment"
    ANOMALY = "anomaly"


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
    category: Category = Field(
        default=Category.WASTE,
        description="waste | rightsizing | commitment | anomaly",
    )
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

    @property
    def savings_by_category(self) -> dict[str, float]:
        """Monthly savings grouped by category (anomalies contribute $0)."""
        out: dict[str, float] = {}
        for f in self.findings:
            out[f.category.value] = round(
                out.get(f.category.value, 0.0) + f.monthly_savings_usd, 2
            )
        return out

    @property
    def anomaly_impact_usd(self) -> float:
        """Total dollar impact of detected cost anomalies (one-off, not
        recurring — kept separate from monthly savings on purpose)."""
        return round(
            sum(
                float(f.evidence.get("impact_usd", 0.0))
                for f in self.findings
                if f.category == Category.ANOMALY
            ),
            2,
        )
