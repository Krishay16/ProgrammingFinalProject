"""Tests for src/data_validation.py using small hand-built periods."""
from datetime import date

from src import config
from src.data_validation import validate_financials, validate_period
from src.models import (CompanyFinancials, CompanyInfo, FinancialPeriod, FinancialValue,
                        SourceType)
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials


def _p(fy: int = 2024, **vals) -> FinancialPeriod:
    """Period from plain floats (full units). Always includes revenue so it is not 'empty'."""
    vals.setdefault("revenue", 100.0)
    return FinancialPeriod(fiscal_year=fy, **{k: FinancialValue(value=v) for k, v in vals.items()})


def _fin(*periods, **company_kw) -> CompanyFinancials:
    return CompanyFinancials(company=CompanyInfo(name="T", **company_kw),
                             source_type=SourceType.MANUAL, periods=list(periods))


def _msgs(issues, level):
    return [i.message for i in issues if i.level == level]


def test_no_periods_is_error():
    issues = validate_financials(_fin())
    assert [i.level for i in issues] == ["error"]


def test_all_fields_missing_is_error():
    issues = validate_period(FinancialPeriod(fiscal_year=2024))
    assert len(issues) == 1 and issues[0].level == "error" and issues[0].fiscal_year == 2024


def test_balance_sheet_mismatch_warns_but_within_tolerance_does_not():
    bad = validate_period(_p(total_assets=1000, total_liabilities=600, total_equity=300))
    assert any("differ" in m for m in _msgs(bad, "warning"))
    ok = validate_period(_p(total_assets=1000, total_liabilities=600, total_equity=395))
    assert not any("differ" in m for m in _msgs(ok, "warning"))


def test_balance_sheet_skipped_when_a_part_is_missing():
    issues = validate_period(_p(total_assets=1000, total_liabilities=600))
    assert not any("differ" in m for m in _msgs(issues, "warning"))


def test_negative_equity_warns():
    issues = validate_period(_p(total_equity=-50))
    assert any("Negative equity" in m for m in _msgs(issues, "warning"))


def test_current_assets_above_total_assets():
    issues = validate_period(_p(current_assets=500, total_assets=400))
    assert any("current assets exceed total assets" in m for m in _msgs(issues, "warning"))


def test_current_liabilities_above_total_liabilities():
    issues = validate_period(_p(current_liabilities=500, total_liabilities=400))
    assert any("current liabilities exceed" in m for m in _msgs(issues, "warning"))


def test_cash_above_current_assets():
    issues = validate_period(_p(cash=300, current_assets=200))
    assert any("cash exceeds current assets" in m for m in _msgs(issues, "warning"))


def test_debt_above_total_liabilities():
    issues = validate_period(_p(short_term_debt=300, long_term_debt=400, total_liabilities=600))
    assert any("inconsistent debt" in m for m in _msgs(issues, "warning"))


def test_gross_profit_mismatch():
    bad = validate_period(_p(revenue=1000, cost_of_revenue=600, gross_profit=500))
    assert any("gross profit" in m for m in _msgs(bad, "warning"))
    ok = validate_period(_p(revenue=1000, cost_of_revenue=600, gross_profit=400))
    assert not any("gross profit" in m for m in _msgs(ok, "warning"))


def test_negative_revenue_and_assets():
    issues = validate_period(_p(revenue=-10, total_assets=-5))
    warnings = _msgs(issues, "warning")
    assert any("revenue is negative" in m for m in warnings)
    assert any("total assets are negative" in m for m in warnings)


def test_negative_capex_and_interest_warn_about_sign_convention():
    issues = validate_period(_p(capex=-50, interest_expense=-5))
    warnings = _msgs(issues, "warning")
    assert any("Capital expenditures" in m for m in warnings)
    assert any("Interest expense" in m for m in warnings)


def test_negative_net_income_is_fine():
    issues = validate_period(_p(net_income=-5))
    assert _msgs(issues, "warning") == []


def test_non_annual_period_warns():
    p = _p()
    p.is_annual = False
    assert any("not an annual" in m for m in _msgs(validate_period(p), "warning"))


def test_missing_fields_listed_as_info_with_readable_names():
    info = _msgs(validate_period(_p()), "info")
    assert len(info) == 1
    assert "Interest expense" in info[0] and "interest_expense" not in info[0]


def test_zero_is_not_reported_as_missing():
    info = _msgs(validate_period(_p(short_term_debt=0.0)), "info")
    assert "Short-term debt" not in info[0]


def test_mixed_currencies_warn():
    a, b = _p(2024), _p(2023)
    b.currency = "EUR"
    issues = validate_financials(_fin(a, b))
    assert any("different currencies" in m for m in _msgs(issues, "warning"))


def test_duplicate_fiscal_years_warn():
    issues = validate_financials(_fin(_p(2024), _p(2024)))
    assert any("more than once" in m for m in _msgs(issues, "warning"))


def test_outdated_statements_warn_using_injected_date():
    p = _p(2020)
    p.period_end = date(2020, 12, 31)
    issues = validate_financials(_fin(p), today=date(2026, 11, 24))
    assert any("outdated" in m for m in _msgs(issues, "warning"))
    recent = validate_financials(_fin(p), today=date(2021, 12, 1))
    assert not any("outdated" in m for m in _msgs(recent, "warning"))


def test_financial_institution_warning():
    issues = validate_financials(_fin(_p(), is_financial_institution=True))
    assert config.FINANCIAL_INSTITUTION_MESSAGE in _msgs(issues, "warning")


def test_healthy_sample_has_no_errors_or_warnings():
    issues = validate_financials(make_sample_financials(), today=date(2025, 6, 1))
    assert [i for i in issues if i.level in ("error", "warning")] == []


def test_incomplete_sample_flags_negative_equity_and_missing_fields():
    issues = validate_financials(make_incomplete_financials(), today=date(2025, 6, 1))
    assert not any(i.level == "error" for i in issues)
    assert any("Negative equity" in i.message for i in issues)
    assert any(i.level == "info" and "Interest expense" in i.message for i in issues)
