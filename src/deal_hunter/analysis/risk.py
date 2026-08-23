"""Layered risk aggregator (rule-first, M5).

Ties together the existing rule-based red flags (`red_flags.py`) with freshness/seller
signals into a single `risk_level` per listing. AI enrichment stays a separate, gated
layer (only invoked for high-value/ambiguous cases upstream); this module does NOT re-implement
the per-flag rules — it aggregates them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from deal_hunter.analysis.schemas import RedFlag


@dataclass
class RiskReport:
    level: str = "none"  # none | low | medium | high | critical
    reasons: list[str] = field(default_factory=list)
    flags: list[RedFlag] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "reasons": self.reasons,
            "flags": [f.dict() for f in self.flags],
        }


_SEV_WEIGHT = {"low": 1, "medium": 2, "high": 4, "critical": 8}


def aggregate_risk(flags: list[RedFlag], stale: bool = False, seller_suspect: bool = False) -> RiskReport:
    """Combine rule flags + contextual signals into an overall risk level.

    - Any 'critical' flag -> critical (scam class).
    - High suspicion (>=2 high, or seller_suspect + flags) -> high.
    - A single high, or >=2 medium, or stale+suspect -> medium.
    - Otherwise low/none.
    """
    report = RiskReport(flags=flags)
    if any(f.severity == "critical" for f in flags):
        report.level = "critical"
        report.reasons.append("Critical red flag(s) present — likely scam/defective.")
        return report

    weight = sum(_SEV_WEIGHT.get(f.severity, 1) for f in flags)
    if seller_suspect:
        weight += 3  # repeat suspect seller raises overall risk
        report.reasons.append("Seller is flagged as suspect.")

    high_count = sum(1 for f in flags if f.severity == "high")
    if weight >= 8 or high_count >= 2:
        report.level = "high"
        report.reasons.append(f"{len(flags)} flag(s), aggregate weight {weight}.")
    elif weight >= 4 or (stale and seller_suspect):
        report.level = "medium"
        report.reasons.append(f"{len(flags)} medium+trade flags.")
    elif weight > 0:
        report.level = "low"
        report.reasons.append("Minor flags present; verify condition.")
    else:
        report.level = "none"
    return report
