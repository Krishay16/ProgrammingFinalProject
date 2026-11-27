"""Illustrative stress scenario for SolvIQ. Owned by Person 4.

Applies simple percentage shocks to a COPY of the latest reported period and recomputes the
ratios and the illustrative score. The result is labelled config.SCENARIO_LABEL: it is an
illustration, NOT reported financials and NOT a forecast.

Method (latest period only; the original data is never modified):
    revenue           *= (1 + revenue_change_pct)
    ebit              += |ebit| * ebit_change_pct   (same as *= (1 + e) when ebit >= 0;
                                                      a decline makes a loss bigger)
    short/long debt   *= (1 + debt_change_pct)
    interest_expense  *= (1 + interest_change_pct)
    ebitda (reported) += the same absolute change as ebit
Everything else is unchanged. A missing value stays missing (None), never 0.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src import config
from src.credit_scoring import compute_credit_score
from src.financial_calculations import compute_ratios
from src.models import (FIELD_LABELS, CompanyFinancials, CreditScore, FinancialPeriod, FinancialValue,
                        Provenance, RatioResult, ValueOrigin, VerificationStatus)

SCENARIO_NOTE = "Illustrative stress scenario"
MIN_CHANGE, MAX_CHANGE = -0.9, 2.0

# Plain-English simplifications that ALWAYS apply.
BASE_ASSUMPTIONS: list[str] = [
    "Only the latest reported fiscal year is stressed; earlier years are unchanged and are "
    "used only for revenue growth.",
    "Cash, equity, total assets, total liabilities, current assets and current liabilities "
    "are not adjusted.",
    "Net income, depreciation and amortization, operating cash flow and capital "
    "expenditures are not adjusted, so the EBIT shock does not flow through to free cash "
    "flow.",
    "Revenue and EBIT are shocked independently. A revenue cut alone (EBIT unchanged) "
    "mechanically raises operating margin and FCF margin, so it is not a realistic "
    "downside on its own. Use a combined revenue + EBIT shock (e.g. the 'Revenue -10% and EBIT -25%' "
    "preset) for a downside view.",
    "A debt change does not change cash (no new borrowing proceeds or repayments are "
    "modelled), and interest expense is changed only by its own slider, not re-derived "
    "from the debt level.",
    "A missing value stays missing; it is never filled in by the scenario.",
]


class ScenarioInputs(BaseModel):
    """Percentage shocks as decimals (-0.20 = -20%), each bounded -0.9 .. +2.0."""

    revenue_change_pct: float = Field(default=0.0, ge=MIN_CHANGE, le=MAX_CHANGE)
    ebit_change_pct: float = Field(default=0.0, ge=MIN_CHANGE, le=MAX_CHANGE)
    debt_change_pct: float = Field(default=0.0, ge=MIN_CHANGE, le=MAX_CHANGE)
    interest_change_pct: float = Field(default=0.0, ge=MIN_CHANGE, le=MAX_CHANGE)


class ScenarioResult(BaseModel):
    """Reported (base) versus stressed ratios and scores for the latest period."""

    base: dict[str, RatioResult]
    stressed: dict[str, RatioResult]
    base_score: CreditScore
    stressed_score: CreditScore
    stressed_period: FinancialPeriod
    label: str = config.SCENARIO_LABEL
    assumptions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _derived(old: FinancialValue, new_value: float, source_type) -> FinancialValue:
    """New value marked DERIVED with the scenario note; provenance is copied, not shared.

    A stressed number is never a matched source fact: it is UNVERIFIED and carries no
    original filing text. source_type / source_ref / location / tag are kept for tracing.
    """
    if old.provenance is not None:
        prov = old.provenance.model_copy(
            update={"origin": ValueOrigin.DERIVED, "note": SCENARIO_NOTE,
                    "verification": VerificationStatus.UNVERIFIED, "original_text": None})
    else:
        prov = Provenance(source_type=source_type, source_ref=SCENARIO_NOTE,
                          origin=ValueOrigin.DERIVED, note=SCENARIO_NOTE,
                          verification=VerificationStatus.UNVERIFIED)
    return FinancialValue(value=new_value, provenance=prov)


def _scale(p: FinancialPeriod, field: str, pct: float, source_type) -> bool:
    """Multiply a field by (1 + pct) in place on the COPY. Returns True if it changed."""
    old = getattr(p, field)
    if pct == 0 or old.value is None:
        return False
    setattr(p, field, _derived(old, old.value * (1 + pct), source_type))
    return True


def _pct_text(pct: float) -> str:
    return f"{pct * 100:+g}%"


def _stress_ebit(p: FinancialPeriod, pct: float, source_type) -> tuple[Optional[float],
                                                                       list[str]]:
    """Apply the EBIT shock and move reported EBITDA by the same amount.

    Returns (absolute EBIT change or None, assumption texts).
    """
    notes: list[str] = []
    ebit = p.get("ebit")
    if pct == 0:
        return None, notes
    if ebit is None:
        notes.append("EBIT is missing, so the EBIT shock could not be applied; EBITDA is "
                     "left unchanged.")
        return None, notes
    delta = abs(ebit) * pct
    setattr(p, "ebit", _derived(p.ebit, ebit + delta, source_type))
    if ebit < 0:
        notes.append(f"EBIT is negative (an operating loss), so the {_pct_text(pct)} change "
                     "is applied to its absolute value: a decline makes the loss larger, "
                     "an increase makes it smaller.")
    if p.get("ebitda") is not None:
        setattr(p, "ebitda", _derived(p.ebitda, p.get("ebitda") + delta, source_type))
        notes.append("Reported EBITDA is moved by the same absolute amount as EBIT "
                     "(depreciation and amortization unchanged).")
    else:
        notes.append("EBITDA is not reported; where it is needed it is derived as stressed "
                     "EBIT + depreciation and amortization.")
    return delta, notes


def stress_period(p: FinancialPeriod, s: ScenarioInputs,
                  source_type) -> tuple[FinancialPeriod, list[str]]:
    """Deep copy of `p` with the shocks applied, plus scenario-specific notes."""
    out = p.model_copy(deep=True)
    notes: list[str] = []
    for field, pct in (("revenue", s.revenue_change_pct),
                       ("short_term_debt", s.debt_change_pct),
                       ("long_term_debt", s.debt_change_pct),
                       ("interest_expense", s.interest_change_pct)):
        if pct != 0 and out.get(field) is None:
            notes.append(f"{FIELD_LABELS[field]} is missing, so its "
                         f"{_pct_text(pct)} shock could not be applied.")
        _scale(out, field, pct, source_type)
    _, ebit_notes = _stress_ebit(out, s.ebit_change_pct, source_type)
    return out, notes + ebit_notes


def describe_inputs(s: ScenarioInputs) -> str:
    """One line summarising the shocks, e.g. 'Revenue +0%, EBIT -20%, ...'."""
    return (f"Shocks applied: revenue {_pct_text(s.revenue_change_pct)}, EBIT "
            f"{_pct_text(s.ebit_change_pct)}, short- and long-term debt "
            f"{_pct_text(s.debt_change_pct)}, interest expense "
            f"{_pct_text(s.interest_change_pct)}.")


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------
def run_scenario(f: CompanyFinancials, s: ScenarioInputs) -> ScenarioResult:
    """Apply the stress to a COPY of the latest period and recompute ratios and scores.

    Raises ValueError if `f` has no periods (the page checks this first).
    """
    latest = f.latest()
    if latest is None:
        raise ValueError("No financial periods are available, so there is nothing to "
                         "stress.")
    prev = f.period(latest.fiscal_year - 1)
    stressed_period, notes = stress_period(latest, s, f.source_type)

    base = compute_ratios(latest, prev)
    stressed = compute_ratios(stressed_period, prev)
    fy = latest.fiscal_year
    stressed_f = f.model_copy(update={"periods": [stressed_period, *f.periods[1:]]})

    return ScenarioResult(
        base=base,
        stressed=stressed,
        base_score=compute_credit_score({fy: base}, f),
        stressed_score=compute_credit_score({fy: stressed}, stressed_f),
        stressed_period=stressed_period,
        assumptions=[describe_inputs(s), *notes, *BASE_ASSUMPTIONS],
    )
