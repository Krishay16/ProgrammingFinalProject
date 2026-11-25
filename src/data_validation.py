"""Sanity checks on financial data before analysis. Owned by Person 1.

Rules never raise on bad data: they return a list of ValidationIssue.
A missing value (None) is skipped by every rule, never treated as 0.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from src import config
from src.models import (ALL_FIELDS, FIELD_LABELS, CompanyFinancials, FinancialPeriod,
                        ValidationIssue)

TOLERANCE = 0.01          # 1% relative tolerance for accounting identities
OUTDATED_MONTHS = 18      # latest period end older than this -> "may be outdated"


def _issue(level: str, message: str, fiscal_year: Optional[int] = None,
           field: Optional[str] = None) -> ValidationIssue:
    return ValidationIssue(level=level, message=message, field=field, fiscal_year=fiscal_year)


def _differs(a: float, b: float, tol: float = TOLERANCE) -> bool:
    """True if a and b differ by more than tol relative to the larger magnitude."""
    scale = max(abs(a), abs(b))
    if scale == 0:
        return False
    return abs(a - b) / scale > tol


def validate_period(p: FinancialPeriod) -> list[ValidationIssue]:
    """Validate one period. Returns errors, warnings and info messages."""
    issues: list[ValidationIssue] = []
    fy = p.fiscal_year
    missing = p.missing_fields()

    if len(missing) == len(ALL_FIELDS):
        issues.append(_issue("error", f"FY{fy}: no financial values were provided for this period.",
                             fy))
        return issues

    ta, tl, te = p.get("total_assets"), p.get("total_liabilities"), p.get("total_equity")
    ca, cl, cash = p.get("current_assets"), p.get("current_liabilities"), p.get("cash")

    if ta is not None and tl is not None and te is not None and _differs(ta, tl + te):
        issues.append(_issue(
            "warning",
            f"FY{fy}: total assets ({ta:,.0f}) differ from total liabilities + equity "
            f"({tl + te:,.0f}) by more than {TOLERANCE:.0%}. Please check the balance sheet.",
            fy, "total_assets"))

    if te is not None and te < 0:
        issues.append(_issue(
            "warning",
            f"FY{fy}: Negative equity: leverage ratios based on equity are not meaningful.",
            fy, "total_equity"))

    if ca is not None and ta is not None and ca > ta:
        issues.append(_issue("warning", f"FY{fy}: current assets exceed total assets.",
                             fy, "current_assets"))
    if cl is not None and tl is not None and cl > tl:
        issues.append(_issue("warning", f"FY{fy}: current liabilities exceed total liabilities.",
                             fy, "current_liabilities"))
    if cash is not None and ca is not None and cash > ca:
        issues.append(_issue("warning", f"FY{fy}: cash exceeds current assets.", fy, "cash"))

    std, ltd = p.get("short_term_debt"), p.get("long_term_debt")
    if std is not None and ltd is not None and tl is not None and std + ltd > tl:
        issues.append(_issue(
            "warning",
            f"FY{fy}: short-term plus long-term debt ({std + ltd:,.0f}) exceeds total "
            f"liabilities ({tl:,.0f}): inconsistent debt figures.", fy, "long_term_debt"))

    rev, cogs, gp = p.get("revenue"), p.get("cost_of_revenue"), p.get("gross_profit")
    if rev is not None and cogs is not None and gp is not None and _differs(gp, rev - cogs):
        issues.append(_issue(
            "warning",
            f"FY{fy}: gross profit ({gp:,.0f}) differs from revenue minus cost of revenue "
            f"({rev - cogs:,.0f}) by more than {TOLERANCE:.0%}.", fy, "gross_profit"))

    if rev is not None and rev < 0:
        issues.append(_issue("warning", f"FY{fy}: revenue is negative.", fy, "revenue"))
    if ta is not None and ta < 0:
        issues.append(_issue("warning", f"FY{fy}: total assets are negative.", fy, "total_assets"))
    for field in ("capex", "interest_expense"):
        v = p.get(field)
        if v is not None and v < 0:
            issues.append(_issue(
                "warning",
                f"FY{fy}: {FIELD_LABELS[field]} is negative, but it should be entered as a "
                "positive amount (the size of the outflow/expense).", fy, field))

    if not p.is_annual:
        issues.append(_issue("warning", f"FY{fy}: this is not an annual period.", fy))

    if missing:
        labels = ", ".join(FIELD_LABELS[f] for f in missing)
        issues.append(_issue("info", f"FY{fy}: missing values: {labels}.", fy))
    return issues


def validate_financials(f: CompanyFinancials, today: Optional[date] = None) -> list[ValidationIssue]:
    """Validate a whole CompanyFinancials (all periods plus cross-period checks).

    `today` is only for tests; it defaults to the current date.
    """
    issues: list[ValidationIssue] = []

    if f.company.is_financial_institution:
        issues.append(_issue("warning", config.FINANCIAL_INSTITUTION_MESSAGE))

    if not f.periods:
        issues.append(_issue("error", "No financial periods were provided."))
        return issues

    for p in f.periods:
        issues.extend(validate_period(p))

    years = [p.fiscal_year for p in f.periods]
    for year in sorted({y for y in years if years.count(y) > 1}, reverse=True):
        issues.append(_issue("warning", f"FY{year} appears more than once.", year))

    currencies = {p.currency for p in f.periods}
    if len(currencies) > 1:
        issues.append(_issue(
            "warning",
            "Periods use different currencies (" + ", ".join(sorted(currencies)) +
            "). Currencies are never converted, so comparisons across years may be wrong."))

    latest_end = max((p.period_end for p in f.periods if p.period_end), default=None)
    if latest_end is not None:
        ref = today or date.today()
        months = (ref.year - latest_end.year) * 12 + (ref.month - latest_end.month)
        if months > OUTDATED_MONTHS:
            issues.append(_issue(
                "warning",
                f"The latest period ended on {latest_end.isoformat()}: statements may be "
                "outdated."))
    return issues
