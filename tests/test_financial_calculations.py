"""Tests for src/financial_calculations.py. Owned by Person 4.

Every expected value is hand-calculated and written as arithmetic in a comment, so it can be
checked with a calculator. Small periods are built with plain round numbers (units do not
matter for ratios); the SYNTHETIC fixtures are checked at the end (values there are given in
millions and stored x 1_000_000).
"""
from __future__ import annotations

from typing import Optional

import pytest

from src import financial_calculations as fc
from src.models import FinancialPeriod, FinancialValue, RatioStatus
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials

VALID = RatioStatus.VALID
UNAVAILABLE = RatioStatus.UNAVAILABLE
UNDEFINED = RatioStatus.UNDEFINED
M = 1_000_000.0  # fixture values are in millions

CONTRACT_KEYS = [
    "current_ratio", "cash_ratio", "working_capital", "total_debt", "debt_to_equity",
    "debt_to_assets", "net_debt", "net_debt_to_ebitda", "operating_margin",
    "net_profit_margin", "return_on_assets", "interest_coverage", "free_cash_flow",
    "fcf_margin", "revenue_growth",
]


def make_period(fiscal_year: int = 2024, currency: str = "USD", is_annual: bool = True,
                **values: Optional[float]) -> FinancialPeriod:
    """Period with only the given fields set; every other field is missing (None)."""
    return FinancialPeriod(fiscal_year=fiscal_year, currency=currency, is_annual=is_annual,
                           **{k: FinancialValue(value=v) for k, v in values.items()})


def assert_valid(result, expected: float) -> None:
    assert result.status == VALID, result.explanation
    assert result.value == pytest.approx(expected)


def assert_not_valid(result, status: RatioStatus, text: str) -> None:
    assert result.status == status
    assert result.value is None
    assert text.lower() in result.explanation.lower()


# ======================================================================================
# safe_divide
# ======================================================================================
class TestSafeDivide:
    def test_normal(self):
        # 500 / 250 = 2.0
        assert fc.safe_divide(500, 250) == (pytest.approx(2.0), VALID, "")

    def test_numerator_missing(self):
        value, status, reason = fc.safe_divide(None, 250, numerator_name="Cash")
        assert (value, status) == (None, UNAVAILABLE)
        assert reason == "Cash is missing."

    def test_denominator_missing(self):
        value, status, reason = fc.safe_divide(500, None, denominator_name="Revenue")
        assert (value, status) == (None, UNAVAILABLE)
        assert reason == "Revenue is missing."

    def test_zero_denominator(self):
        value, status, reason = fc.safe_divide(500, 0)
        assert (value, status) == (None, UNDEFINED)
        assert "denominator is zero" in reason

    def test_negative_denominator_when_positive_required(self):
        value, status, reason = fc.safe_divide(500, -250, require_positive_denominator=True)
        assert (value, status) == (None, UNDEFINED)
        assert "negative" in reason

    def test_negative_denominator_allowed_by_default(self):
        # 500 / -250 = -2.0
        value, status, _ = fc.safe_divide(500, -250)
        assert status == VALID and value == pytest.approx(-2.0)

    def test_negative_numerator_is_valid(self):
        # -500 / 250 = -2.0
        value, status, _ = fc.safe_divide(-500, 250, require_positive_denominator=True)
        assert status == VALID and value == pytest.approx(-2.0)


# ======================================================================================
# total_debt_value / ebitda_value helpers
# ======================================================================================
class TestHelpers:
    def test_total_debt_value_both_known(self):
        # 100 + 400 = 500
        p = make_period(short_term_debt=100, long_term_debt=400)
        assert fc.total_debt_value(p) == pytest.approx(500)

    def test_total_debt_value_one_missing_is_none_not_partial(self):
        p = make_period(long_term_debt=400)  # short_term_debt missing
        assert fc.total_debt_value(p) is None

    def test_total_debt_value_explicit_zero_component(self):
        # analyst typed 0 for short-term debt: 0 + 400 = 400
        p = make_period(short_term_debt=0, long_term_debt=400)
        assert fc.total_debt_value(p) == pytest.approx(400)

    def test_ebitda_reported_takes_precedence(self):
        # reported 250 is used even though EBIT + D&A = 150 + 50 = 200
        p = make_period(ebitda=250, ebit=150, depreciation_amortization=50)
        value, note = fc.ebitda_value(p)
        assert value == pytest.approx(250)
        assert note == ""

    def test_ebitda_derived_from_ebit_plus_da(self):
        # 150 + 50 = 200
        p = make_period(ebit=150, depreciation_amortization=50)
        value, note = fc.ebitda_value(p)
        assert value == pytest.approx(200)
        assert "derived" in note

    def test_ebitda_not_derivable(self):
        p = make_period(ebit=150)  # D&A missing, EBITDA missing
        value, note = fc.ebitda_value(p)
        assert value is None
        assert "cannot be derived" in note


# ======================================================================================
# Liquidity
# ======================================================================================
class TestCurrentRatio:
    def test_normal_and_metadata(self):
        r = fc.current_ratio(make_period(current_assets=500, current_liabilities=250))
        assert_valid(r, 2.0)  # 500 / 250 = 2.0
        assert (r.key, r.label, r.category, r.unit, r.fiscal_year) == (
            "current_ratio", "Current Ratio", "liquidity", "x", 2024)
        assert r.formula == "Current Assets / Current Liabilities"
        assert r.inputs == {"current_assets": 500, "current_liabilities": 250}

    def test_missing_input(self):
        r = fc.current_ratio(make_period(current_assets=500))
        assert_not_valid(r, UNAVAILABLE, "Current liabilities is missing")
        assert r.inputs == {"current_assets": 500, "current_liabilities": None}

    def test_zero_denominator(self):
        r = fc.current_ratio(make_period(current_assets=500, current_liabilities=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_denominator(self):
        r = fc.current_ratio(make_period(current_assets=500, current_liabilities=-250))
        assert_not_valid(r, UNDEFINED, "current liabilities are negative")


class TestCashRatio:
    def test_normal(self):
        # 100 / 400 = 0.25
        assert_valid(fc.cash_ratio(make_period(cash=100, current_liabilities=400)), 0.25)

    def test_missing_input(self):
        r = fc.cash_ratio(make_period(current_liabilities=400))
        assert_not_valid(r, UNAVAILABLE, "Cash and cash equivalents is missing")

    def test_zero_denominator(self):
        r = fc.cash_ratio(make_period(cash=100, current_liabilities=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_denominator(self):
        r = fc.cash_ratio(make_period(cash=100, current_liabilities=-400))
        assert_not_valid(r, UNDEFINED, "negative")


class TestWorkingCapital:
    def test_normal(self):
        r = fc.working_capital(make_period(current_assets=500, current_liabilities=200))
        assert_valid(r, 300)  # 500 - 200 = 300
        assert r.unit == "currency"

    def test_missing_input(self):
        r = fc.working_capital(make_period(current_assets=500))
        assert_not_valid(r, UNAVAILABLE, "is missing")

    def test_zero_result_is_valid(self):
        # no denominator; equal values give 500 - 500 = 0 (valid, not "missing")
        assert_valid(fc.working_capital(make_period(current_assets=500,
                                                    current_liabilities=500)), 0)

    def test_negative_is_valid_and_explained(self):
        r = fc.working_capital(make_period(current_assets=200, current_liabilities=500))
        assert_valid(r, -300)  # 200 - 500 = -300
        assert "negative working capital" in r.explanation.lower()


# ======================================================================================
# Leverage
# ======================================================================================
class TestTotalDebt:
    def test_normal(self):
        r = fc.total_debt(make_period(short_term_debt=100, long_term_debt=400))
        assert_valid(r, 500)  # 100 + 400 = 500
        assert (r.category, r.unit) == ("leverage", "currency")

    def test_one_component_missing(self):
        r = fc.total_debt(make_period(long_term_debt=400))
        assert_not_valid(r, UNAVAILABLE, "Short-term debt")
        assert "enter 0" in r.explanation
        assert r.inputs == {"short_term_debt": None, "long_term_debt": 400}

    def test_both_components_missing(self):
        r = fc.total_debt(make_period())
        assert_not_valid(r, UNAVAILABLE, "are missing")

    def test_explicit_zero_components(self):
        # 0 + 0 = 0 (analyst confirmed the company has no debt)
        assert_valid(fc.total_debt(make_period(short_term_debt=0, long_term_debt=0)), 0)


class TestDebtToEquity:
    def test_normal(self):
        # (100 + 400) / 1000 = 500 / 1000 = 0.5
        r = fc.debt_to_equity(make_period(short_term_debt=100, long_term_debt=400,
                                          total_equity=1000))
        assert_valid(r, 0.5)
        assert r.inputs == {"short_term_debt": 100, "long_term_debt": 400,
                            "total_equity": 1000}

    def test_missing_equity(self):
        r = fc.debt_to_equity(make_period(short_term_debt=100, long_term_debt=400))
        assert_not_valid(r, UNAVAILABLE, "Total shareholders' equity is missing")

    def test_missing_debt_component(self):
        r = fc.debt_to_equity(make_period(long_term_debt=400, total_equity=1000))
        assert_not_valid(r, UNAVAILABLE, "Short-term debt")

    def test_zero_equity(self):
        r = fc.debt_to_equity(make_period(short_term_debt=100, long_term_debt=400,
                                          total_equity=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_equity(self):
        r = fc.debt_to_equity(make_period(short_term_debt=100, long_term_debt=400,
                                          total_equity=-500))
        assert_not_valid(r, UNDEFINED, "negative equity: ratio not meaningful")


class TestDebtToAssets:
    def test_normal(self):
        # (100 + 400) / 2000 = 500 / 2000 = 0.25 (25%)
        r = fc.debt_to_assets(make_period(short_term_debt=100, long_term_debt=400,
                                          total_assets=2000))
        assert_valid(r, 0.25)
        assert r.unit == "%"

    def test_missing_input(self):
        r = fc.debt_to_assets(make_period(short_term_debt=100, long_term_debt=400))
        assert_not_valid(r, UNAVAILABLE, "Total assets is missing")

    def test_zero_denominator(self):
        r = fc.debt_to_assets(make_period(short_term_debt=100, long_term_debt=400,
                                          total_assets=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_assets(self):
        r = fc.debt_to_assets(make_period(short_term_debt=100, long_term_debt=400,
                                          total_assets=-2000))
        assert_not_valid(r, UNDEFINED, "total assets are negative")


class TestNetDebt:
    def test_normal(self):
        # (100 + 400) - 200 = 300
        r = fc.net_debt(make_period(short_term_debt=100, long_term_debt=400, cash=200))
        assert_valid(r, 300)
        assert r.explanation == ""

    def test_net_cash_is_valid_negative(self):
        # (100 + 400) - 800 = -300 -> net cash position
        r = fc.net_debt(make_period(short_term_debt=100, long_term_debt=400, cash=800))
        assert_valid(r, -300)
        assert "net cash" in r.explanation.lower()

    def test_missing_cash(self):
        r = fc.net_debt(make_period(short_term_debt=100, long_term_debt=400))
        assert_not_valid(r, UNAVAILABLE, "Cash and cash equivalents is missing")

    def test_zero_result(self):
        # no denominator; (100 + 400) - 500 = 0
        assert_valid(fc.net_debt(make_period(short_term_debt=100, long_term_debt=400,
                                             cash=500)), 0)


class TestNetDebtToEbitda:
    def test_normal_reported_ebitda(self):
        # ((100 + 400) - 100) / 200 = 400 / 200 = 2.0
        r = fc.net_debt_to_ebitda(make_period(short_term_debt=100, long_term_debt=400,
                                              cash=100, ebitda=200))
        assert_valid(r, 2.0)
        assert "derived" not in r.explanation

    def test_ebitda_derived_from_ebit_plus_da(self):
        # EBITDA = 150 + 50 = 200 ; ((100 + 400) - 100) / 200 = 2.0
        r = fc.net_debt_to_ebitda(make_period(short_term_debt=100, long_term_debt=400,
                                              cash=100, ebit=150,
                                              depreciation_amortization=50))
        assert_valid(r, 2.0)
        assert "derived" in r.explanation
        assert r.inputs["ebitda"] is None
        assert r.inputs["ebit"] == 150 and r.inputs["depreciation_amortization"] == 50

    def test_net_cash_is_valid_negative(self):
        # ((100 + 400) - 900) / 200 = -400 / 200 = -2.0
        r = fc.net_debt_to_ebitda(make_period(short_term_debt=100, long_term_debt=400,
                                              cash=900, ebitda=200))
        assert_valid(r, -2.0)
        assert "net cash" in r.explanation.lower()

    def test_ebitda_zero(self):
        r = fc.net_debt_to_ebitda(make_period(short_term_debt=100, long_term_debt=400,
                                              cash=100, ebitda=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_ebitda_negative(self):
        r = fc.net_debt_to_ebitda(make_period(short_term_debt=100, long_term_debt=400,
                                              cash=100, ebitda=-200))
        assert_not_valid(r, UNDEFINED, "EBITDA is negative")

    def test_derived_ebitda_negative(self):
        # EBITDA = -100 + 50 = -50 <= 0 -> undefined
        r = fc.net_debt_to_ebitda(make_period(short_term_debt=100, long_term_debt=400,
                                              cash=100, ebit=-100,
                                              depreciation_amortization=50))
        assert_not_valid(r, UNDEFINED, "EBITDA is negative")

    def test_ebitda_missing_and_not_derivable(self):
        r = fc.net_debt_to_ebitda(make_period(short_term_debt=100, long_term_debt=400,
                                              cash=100, ebit=150))
        assert_not_valid(r, UNAVAILABLE, "cannot be derived")

    def test_debt_component_missing(self):
        r = fc.net_debt_to_ebitda(make_period(long_term_debt=400, cash=100, ebitda=200))
        assert_not_valid(r, UNAVAILABLE, "Short-term debt")


# ======================================================================================
# Profitability
# ======================================================================================
class TestOperatingMargin:
    def test_normal(self):
        # 250 / 1000 = 0.25 (25%)
        r = fc.operating_margin(make_period(ebit=250, revenue=1000))
        assert_valid(r, 0.25)
        assert (r.category, r.unit) == ("profitability", "%")

    def test_operating_loss_is_valid(self):
        # -100 / 1000 = -0.1
        assert_valid(fc.operating_margin(make_period(ebit=-100, revenue=1000)), -0.1)

    def test_missing_input(self):
        r = fc.operating_margin(make_period(revenue=1000))
        assert_not_valid(r, UNAVAILABLE, "Operating income (EBIT) is missing")

    def test_zero_revenue(self):
        r = fc.operating_margin(make_period(ebit=250, revenue=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_revenue(self):
        r = fc.operating_margin(make_period(ebit=250, revenue=-1000))
        assert_not_valid(r, UNDEFINED, "revenue is negative")


class TestNetProfitMargin:
    def test_normal(self):
        # 100 / 1000 = 0.1 (10%)
        assert_valid(fc.net_profit_margin(make_period(net_income=100, revenue=1000)), 0.1)

    def test_net_loss_is_valid(self):
        # -50 / 1000 = -0.05
        assert_valid(fc.net_profit_margin(make_period(net_income=-50, revenue=1000)), -0.05)

    def test_missing_input(self):
        r = fc.net_profit_margin(make_period(revenue=1000))
        assert_not_valid(r, UNAVAILABLE, "Net income is missing")

    def test_zero_revenue(self):
        r = fc.net_profit_margin(make_period(net_income=100, revenue=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_revenue(self):
        r = fc.net_profit_margin(make_period(net_income=100, revenue=-1000))
        assert_not_valid(r, UNDEFINED, "revenue is negative")


class TestReturnOnAssets:
    def test_normal_says_end_of_period(self):
        # 100 / 2000 = 0.05 (5%)
        r = fc.return_on_assets(make_period(net_income=100, total_assets=2000))
        assert_valid(r, 0.05)
        assert "end-of-period" in r.explanation

    def test_net_loss_is_valid(self):
        # -100 / 2000 = -0.05
        assert_valid(fc.return_on_assets(make_period(net_income=-100, total_assets=2000)),
                     -0.05)

    def test_missing_input(self):
        r = fc.return_on_assets(make_period(total_assets=2000))
        assert_not_valid(r, UNAVAILABLE, "Net income is missing")

    def test_zero_assets(self):
        r = fc.return_on_assets(make_period(net_income=100, total_assets=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_assets(self):
        r = fc.return_on_assets(make_period(net_income=100, total_assets=-2000))
        assert_not_valid(r, UNDEFINED, "total assets are negative")


# ======================================================================================
# Coverage
# ======================================================================================
class TestInterestCoverage:
    def test_normal(self):
        # 500 / 100 = 5.0
        r = fc.interest_coverage(make_period(ebit=500, interest_expense=100))
        assert_valid(r, 5.0)
        assert (r.category, r.unit) == ("coverage", "x")

    def test_negative_ebit_is_valid(self):
        # -200 / 100 = -2.0
        r = fc.interest_coverage(make_period(ebit=-200, interest_expense=100))
        assert_valid(r, -2.0)
        assert "negative ebit" in r.explanation.lower()

    def test_interest_expense_missing(self):
        r = fc.interest_coverage(make_period(ebit=500))
        assert_not_valid(r, UNAVAILABLE, "Interest expense is missing")

    def test_ebit_missing(self):
        r = fc.interest_coverage(make_period(interest_expense=100))
        assert_not_valid(r, UNAVAILABLE, "Operating income (EBIT) is missing")

    def test_interest_expense_zero(self):
        r = fc.interest_coverage(make_period(ebit=500, interest_expense=0))
        assert_not_valid(r, UNDEFINED,
                         "no interest expense reported; coverage not meaningful")

    def test_interest_expense_negative(self):
        r = fc.interest_coverage(make_period(ebit=500, interest_expense=-100))
        assert_not_valid(r, UNDEFINED, "inconsistent sign")


# ======================================================================================
# Cash flow
# ======================================================================================
class TestFreeCashFlow:
    def test_normal(self):
        # 800 - 300 = 500
        r = fc.free_cash_flow(make_period(operating_cash_flow=800, capex=300))
        assert_valid(r, 500)
        assert (r.category, r.unit) == ("cash_flow", "currency")

    def test_negative_fcf_is_valid(self):
        # 300 - 800 = -500
        r = fc.free_cash_flow(make_period(operating_cash_flow=300, capex=800))
        assert_valid(r, -500)
        assert "negative free cash flow" in r.explanation.lower()

    def test_zero_result(self):
        # no denominator; 300 - 300 = 0
        assert_valid(fc.free_cash_flow(make_period(operating_cash_flow=300, capex=300)), 0)

    def test_missing_capex(self):
        r = fc.free_cash_flow(make_period(operating_cash_flow=800))
        assert_not_valid(r, UNAVAILABLE, "Capital expenditures is missing")

    def test_negative_capex_inconsistent_sign(self):
        r = fc.free_cash_flow(make_period(operating_cash_flow=800, capex=-300))
        assert_not_valid(r, UNDEFINED, "inconsistent sign")


class TestFcfMargin:
    def test_normal(self):
        # (800 - 300) / 1000 = 500 / 1000 = 0.5 (50%)
        r = fc.fcf_margin(make_period(operating_cash_flow=800, capex=300, revenue=1000))
        assert_valid(r, 0.5)
        assert r.unit == "%"

    def test_negative_fcf_is_valid(self):
        # (300 - 800) / 1000 = -500 / 1000 = -0.5
        assert_valid(fc.fcf_margin(make_period(operating_cash_flow=300, capex=800,
                                               revenue=1000)), -0.5)

    def test_missing_revenue(self):
        r = fc.fcf_margin(make_period(operating_cash_flow=800, capex=300))
        assert_not_valid(r, UNAVAILABLE, "Revenue is missing")

    def test_missing_capex(self):
        r = fc.fcf_margin(make_period(operating_cash_flow=800, revenue=1000))
        assert_not_valid(r, UNAVAILABLE, "Capital expenditures is missing")

    def test_zero_revenue(self):
        r = fc.fcf_margin(make_period(operating_cash_flow=800, capex=300, revenue=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_negative_revenue(self):
        r = fc.fcf_margin(make_period(operating_cash_flow=800, capex=300, revenue=-1000))
        assert_not_valid(r, UNDEFINED, "revenue is negative")

    def test_negative_capex_inconsistent_sign(self):
        r = fc.fcf_margin(make_period(operating_cash_flow=800, capex=-300, revenue=1000))
        assert_not_valid(r, UNDEFINED, "inconsistent sign")


# ======================================================================================
# Growth
# ======================================================================================
class TestRevenueGrowth:
    def test_normal(self):
        # 1100 / 1000 - 1 = 0.1 (10%)
        r = fc.revenue_growth(make_period(2024, revenue=1100), make_period(2023, revenue=1000))
        assert_valid(r, 0.1)
        assert r.inputs == {"revenue": 1100, "prior_revenue": 1000}
        assert (r.category, r.unit) == ("growth", "%")

    def test_decline_is_valid(self):
        # 900 / 1000 - 1 = -0.1
        assert_valid(fc.revenue_growth(make_period(2024, revenue=900),
                                       make_period(2023, revenue=1000)), -0.1)

    def test_no_prior_period(self):
        r = fc.revenue_growth(make_period(2024, revenue=1100), None)
        assert_not_valid(r, UNAVAILABLE, "No prior-year period")

    def test_gap_year(self):
        r = fc.revenue_growth(make_period(2024, revenue=1100), make_period(2022, revenue=1000))
        assert_not_valid(r, UNAVAILABLE, "Prior period is FY2022, not FY2023")

    def test_different_currency(self):
        r = fc.revenue_growth(make_period(2024, currency="EUR", revenue=1100),
                              make_period(2023, currency="USD", revenue=1000))
        assert_not_valid(r, UNDEFINED, "Different currencies (USD vs EUR)")

    def test_prior_revenue_zero(self):
        r = fc.revenue_growth(make_period(2024, revenue=1100), make_period(2023, revenue=0))
        assert_not_valid(r, UNDEFINED, "denominator is zero")

    def test_prior_revenue_negative(self):
        r = fc.revenue_growth(make_period(2024, revenue=1100),
                              make_period(2023, revenue=-1000))
        assert_not_valid(r, UNDEFINED, "Prior-year revenue is negative")

    def test_current_revenue_negative(self):
        r = fc.revenue_growth(make_period(2024, revenue=-1100),
                              make_period(2023, revenue=1000))
        assert_not_valid(r, UNDEFINED, "Current revenue is negative")

    def test_prior_revenue_missing(self):
        r = fc.revenue_growth(make_period(2024, revenue=1100), make_period(2023))
        assert_not_valid(r, UNAVAILABLE, "Prior-year revenue is missing")

    def test_current_revenue_missing(self):
        r = fc.revenue_growth(make_period(2024), make_period(2023, revenue=1000))
        assert_not_valid(r, UNAVAILABLE, "Revenue is missing")

    def test_not_annual(self):
        r = fc.revenue_growth(make_period(2024, is_annual=False, revenue=1100),
                              make_period(2023, revenue=1000))
        assert_not_valid(r, UNDEFINED, "annual")


# ======================================================================================
# compute_ratios / compute_all_ratios
# ======================================================================================
class TestAggregation:
    def test_standard_keys_match_contract(self):
        assert fc.STANDARD_RATIO_KEYS == CONTRACT_KEYS

    def test_compute_ratios_on_empty_period_has_all_keys_and_no_values(self):
        results = fc.compute_ratios(make_period(), None)
        assert list(results) == CONTRACT_KEYS
        for key, r in results.items():
            assert r.key == key
            assert r.status == UNAVAILABLE
            assert r.value is None
            assert r.explanation  # every non-valid result says why

    def test_compute_all_ratios_passes_previous_year(self):
        f = make_sample_financials()
        f.periods = [f.periods[0], f.periods[2]]  # FY2024 and FY2022 only: gap year
        ratios = fc.compute_all_ratios(f)
        assert set(ratios) == {2024, 2022}
        # FY2023 does not exist, so FY2024 gets prev=None
        assert ratios[2024]["revenue_growth"].status == UNAVAILABLE


class TestSampleFinancials:
    """SYNTHETIC healthy company, FY2024/2023/2022, every field filled."""

    @pytest.fixture
    def ratios(self):
        return fc.compute_all_ratios(make_sample_financials())

    def test_all_keys_for_every_year(self, ratios):
        assert set(ratios) == {2024, 2023, 2022}
        for year, by_key in ratios.items():
            assert list(by_key) == CONTRACT_KEYS
            assert all(r.fiscal_year == year for r in by_key.values())

    def test_all_valid_except_first_year_growth(self, ratios):
        for year, by_key in ratios.items():
            for key, r in by_key.items():
                if year == 2022 and key == "revenue_growth":
                    assert r.status == UNAVAILABLE  # no FY2021 in the fixture
                else:
                    assert r.status == VALID, f"FY{year} {key}: {r.explanation}"

    def test_fy2024_values_hand_calculated(self, ratios):
        r = ratios[2024]
        expected = {
            "current_ratio": 4_800 / 2_600,            # = 1.8462
            "cash_ratio": 1_500 / 2_600,               # = 0.5769
            "working_capital": (4_800 - 2_600) * M,    # = 2_200 m
            "total_debt": (400 + 2_800) * M,           # = 3_200 m
            "debt_to_equity": 3_200 / 5_400,           # = 0.5926
            "debt_to_assets": 3_200 / 12_000,          # = 0.2667
            "net_debt": (3_200 - 1_500) * M,           # = 1_700 m
            "net_debt_to_ebitda": 1_700 / 1_800,       # = 0.9444 (reported EBITDA)
            "operating_margin": 1_350 / 9_000,         # = 0.15
            "net_profit_margin": 900 / 9_000,          # = 0.10
            "return_on_assets": 900 / 12_000,          # = 0.075
            "interest_coverage": 1_350 / 150,          # = 9.0
            "free_cash_flow": (1_500 - 600) * M,       # = 900 m
            "fcf_margin": (1_500 - 600) / 9_000,       # = 0.10
            "revenue_growth": 9_000 / 8_400 - 1,       # = 0.0714
        }
        for key, value in expected.items():
            assert r[key].value == pytest.approx(value), key

    def test_growth_other_years_hand_calculated(self, ratios):
        # FY2023: 8_400 / 7_900 - 1 = 0.0633
        assert ratios[2023]["revenue_growth"].value == pytest.approx(8_400 / 7_900 - 1)


class TestIncompleteFinancials:
    """SYNTHETIC: one period, negative equity, missing interest expense, short-term debt
    and all cash-flow fields."""

    @pytest.fixture
    def r(self):
        ratios = fc.compute_all_ratios(make_incomplete_financials())
        assert set(ratios) == {2024}
        assert list(ratios[2024]) == CONTRACT_KEYS
        return ratios[2024]

    def test_valid_ratios_hand_calculated(self, r):
        assert_valid(r["current_ratio"], 900 / 1_100)          # = 0.8182
        assert_valid(r["cash_ratio"], 150 / 1_100)             # = 0.1364
        assert_valid(r["working_capital"], (900 - 1_100) * M)  # = -200 m
        assert_valid(r["operating_margin"], 120 / 2_000)       # = 0.06
        assert_valid(r["net_profit_margin"], -60 / 2_000)      # = -0.03
        assert_valid(r["return_on_assets"], -60 / 3_000)       # = -0.02

    def test_missing_short_term_debt_makes_debt_ratios_unavailable(self, r):
        # short_term_debt is None: never treated as 0, so total debt is unknown.
        # (Missing data is reported before the negative-equity check.)
        for key in ("total_debt", "debt_to_equity", "debt_to_assets", "net_debt",
                    "net_debt_to_ebitda"):
            assert_not_valid(r[key], UNAVAILABLE, "Short-term debt")

    def test_other_unavailable(self, r):
        assert_not_valid(r["interest_coverage"], UNAVAILABLE, "Interest expense is missing")
        # both cash-flow inputs are missing in this fixture -> plural message
        assert_not_valid(r["free_cash_flow"], UNAVAILABLE,
                         "Operating cash flow, Capital expenditures are missing")
        assert_not_valid(r["fcf_margin"], UNAVAILABLE,
                         "Operating cash flow, Capital expenditures are missing")
        assert_not_valid(r["revenue_growth"], UNAVAILABLE, "No prior-year period")

    def test_negative_equity_when_debt_known(self):
        # Same fixture with short-term debt filled in: equity -500 -> UNDEFINED.
        f = make_incomplete_financials()
        f.periods[0].short_term_debt = FinancialValue(value=200 * M)
        r = fc.compute_all_ratios(f)[2024]
        assert_not_valid(r["debt_to_equity"], UNDEFINED,
                         "negative equity: ratio not meaningful")
        # (200 + 1_800) / 3_000 = 0.6667 still valid
        assert_valid(r["debt_to_assets"], 2_000 / 3_000)
