"""Owned by Person 4: one function per ratio, plus compute_ratios / compute_all_ratios."""
from __future__ import annotations

from typing import Optional

from src.models import CompanyFinancials, FinancialPeriod, RatioResult


def current_ratio(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Current Ratio."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def cash_ratio(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Cash Ratio."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def working_capital(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Working Capital."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def total_debt(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Total Debt."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def debt_to_equity(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Debt to Equity."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def debt_to_assets(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Debt to Assets."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def net_debt(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Net Debt."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def net_debt_to_ebitda(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Net Debt to EBITDA."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def operating_margin(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Operating Margin."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def net_profit_margin(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Net Profit Margin."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def return_on_assets(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Return on Assets."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def interest_coverage(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Interest Coverage."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def free_cash_flow(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Free Cash Flow."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def fcf_margin(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """FCF Margin."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def revenue_growth(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Revenue Growth."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def compute_ratios(p: FinancialPeriod,
                   prev: Optional[FinancialPeriod]) -> dict[str, RatioResult]:
    """All 15 standard ratios for one period."""
    raise NotImplementedError("Owned by Person 4, not built yet")


def compute_all_ratios(f: CompanyFinancials) -> dict[int, dict[str, RatioResult]]:
    """fiscal_year -> ratio key -> RatioResult for every period."""
    raise NotImplementedError("Owned by Person 4, not built yet")
