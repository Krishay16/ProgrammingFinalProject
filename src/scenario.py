"""Owned by Person 4: illustrative stress scenario."""
from __future__ import annotations

from pydantic import BaseModel

from src.models import CompanyFinancials


class ScenarioInputs(BaseModel):
    """TODO(Person 4): revenue_change_pct, ebit_change_pct, debt_change_pct,
    interest_change_pct."""


class ScenarioResult(BaseModel):
    """TODO(Person 4): base/stressed ratios and scores, assumptions, label."""


def run_scenario(f: CompanyFinancials, s: ScenarioInputs) -> ScenarioResult:
    """Apply the stress to a COPY of the latest period and recompute."""
    raise NotImplementedError("Owned by Person 4, not built yet")
