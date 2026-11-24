"""Owned by Person 4: rule-based risk alerts."""
from __future__ import annotations

from src.models import CompanyFinancials, RatioResult, RiskAlert


def generate_alerts(ratios: dict[int, dict[str, RatioResult]],
                    f: CompanyFinancials) -> list[RiskAlert]:
    """Screening alerts for the latest year plus trend alerts."""
    raise NotImplementedError("Owned by Person 4, not built yet")
