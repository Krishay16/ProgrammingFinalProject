"""Owned by Person 4: illustrative 0-100 screening score."""
from __future__ import annotations

from src.models import CompanyFinancials, CreditScore, RatioResult

SCORING_CONFIG: dict = {}  # TODO(Person 4): weights and thresholds, documented


def compute_credit_score(ratios: dict[int, dict[str, RatioResult]],
                         f: CompanyFinancials) -> CreditScore:
    """Illustrative score from the latest fiscal year's ratios."""
    raise NotImplementedError("Owned by Person 4, not built yet")
