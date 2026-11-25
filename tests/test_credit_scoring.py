"""Tests for src/credit_scoring.py. Owned by Person 4.

Expected values are hand-calculated; the arithmetic is written next to each one.
Test periods use plain round numbers (units do not matter for ratios). The HEALTHY dict
below is the SYNTHETIC make_sample_financials() FY2024 period, written in millions.
"""
from __future__ import annotations

from typing import Optional

import pytest

from src import config
from src import credit_scoring as cs
from src.financial_calculations import compute_all_ratios
from src.models import (CompanyFinancials, CompanyInfo, CreditScore, FinancialPeriod,
                        FinancialValue, SourceType)
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials

# SYNTHETIC: same numbers as make_sample_financials() FY2024 (in millions).
HEALTHY: dict[str, float] = {
    "cash": 1_500, "current_assets": 4_800, "total_assets": 12_000,
    "current_liabilities": 2_600, "total_liabilities": 6_600,
    "short_term_debt": 400, "long_term_debt": 2_800, "total_equity": 5_400,
    "revenue": 9_000, "cost_of_revenue": 5_850, "gross_profit": 3_150,
    "ebit": 1_350, "ebitda": 1_800, "interest_expense": 150,
    "net_income": 900, "depreciation_amortization": 450,
    "operating_cash_flow": 1_500, "capex": 600,
    "investing_cash_flow": -750, "financing_cash_flow": -500,
}


def company(fi: bool = False, **overrides: Optional[float]) -> CompanyFinancials:
    """SYNTHETIC one-period company: HEALTHY values with `overrides` (None = missing)."""
    values = {**HEALTHY, **overrides}
    period = FinancialPeriod(fiscal_year=2024,
                             **{k: FinancialValue(value=v) for k, v in values.items()})
    return CompanyFinancials(
        company=CompanyInfo(name="Test Co (SYNTHETIC)", is_financial_institution=fi),
        source_type=SourceType.SYNTHETIC, periods=[period])


def score(f: CompanyFinancials) -> CreditScore:
    return cs.compute_credit_score(compute_all_ratios(f), f)


def factor(s: CreditScore, name: str):
    return next(fs for fs in s.factors if fs.factor == name)


# ======================================================================================
# Configuration
# ======================================================================================
def test_weights_sum_to_100():
    # 20 + 25 + 20 + 20 + 15 = 100
    assert sum(f["weight"] for f in cs.SCORING_CONFIG.values()) == 100
    assert {k: v["weight"] for k, v in cs.SCORING_CONFIG.items()} == {
        "liquidity": 20, "leverage": 25, "profitability": 20, "coverage": 20, "cash_flow": 15}


# ======================================================================================
# Band boundaries: every threshold exactly ON the boundary and just past it
# ======================================================================================
@pytest.mark.parametrize("value, fraction", [
    (2.0, 1.0), (1.9999, 0.75), (1.5, 0.75), (1.4999, 0.5),
    (1.0, 0.5), (0.9999, 0.25), (0.8, 0.25), (0.7999, 0.0),
])
def test_current_ratio_bands(value, fraction):
    assert cs.score_ratio("current_ratio", value)[0] == fraction


@pytest.mark.parametrize("value, fraction", [
    (0.5, 1.0), (0.5001, 0.75), (1.0, 0.75), (1.0001, 0.5),
    (2.0, 0.5), (2.0001, 0.25), (3.0, 0.25), (3.0001, 0.0),
])
def test_debt_to_equity_bands(value, fraction):
    assert cs.score_ratio("debt_to_equity", value)[0] == fraction


@pytest.mark.parametrize("value, fraction", [
    (-0.5, 1.0),  # net cash: negative net debt / EBITDA is <= 1.0x -> full marks
    (1.0, 1.0), (1.0001, 0.75), (2.0, 0.75), (2.0001, 0.5),
    (3.0, 0.5), (3.0001, 0.25), (4.0, 0.25), (4.0001, 0.0),
])
def test_net_debt_to_ebitda_bands(value, fraction):
    assert cs.score_ratio("net_debt_to_ebitda", value)[0] == fraction


@pytest.mark.parametrize("value, fraction", [
    (0.15, 1.0), (0.1499, 0.75), (0.08, 0.75), (0.0799, 0.5),
    (0.03, 0.5), (0.0299, 0.25), (0.0, 0.25), (-0.0001, 0.0),
])
def test_operating_margin_bands(value, fraction):
    assert cs.score_ratio("operating_margin", value)[0] == fraction


@pytest.mark.parametrize("value, fraction", [
    (8.0, 1.0), (7.9999, 0.75), (4.0, 0.75), (3.9999, 0.5),
    (2.0, 0.5), (1.9999, 0.25), (1.0, 0.25), (0.9999, 0.0), (-1.0, 0.0),
])
def test_interest_coverage_bands(value, fraction):
    assert cs.score_ratio("interest_coverage", value)[0] == fraction


@pytest.mark.parametrize("value, fraction", [
    (0.10, 1.0), (0.0999, 0.75), (0.05, 0.75), (0.0499, 0.5), (0.0, 0.5), (-0.0001, 0.0),
])
def test_fcf_margin_bands(value, fraction):
    assert cs.score_ratio("fcf_margin", value)[0] == fraction


@pytest.mark.parametrize("current_assets, points", [
    # current liabilities = 100 in every row
    (200, 20.0),   # 200 / 100 = 2.0x   -> >= 2.0 -> 100% x 20 = 20
    (150, 15.0),   # 1.5x               -> 75% x 20 = 15
    (100, 10.0),   # 1.0x               -> 50% x 20 = 10
    (80, 5.0),     # 0.8x               -> 25% x 20 = 5
    (79, 0.0),     # 0.79x              -> 0
])
def test_liquidity_points_from_real_division(current_assets, points):
    s = score(company(current_assets=current_assets, current_liabilities=100))
    assert factor(s, "liquidity").points == points


def test_band_explanation_wording():
    # 4_200 / 2_600 = 1.615x -> 1.5-2.0x band -> 75% x 20 = 15
    s = score(company(current_assets=4_200))
    assert factor(s, "liquidity").explanation == (
        "Current ratio 1.62x is in the 1.5-2.0x band: 15 of 20 points.")


@pytest.mark.parametrize("total, label", [
    (100, "Lower Indicative Financial Risk"), (80, "Lower Indicative Financial Risk"),
    (79.999, "Moderate Indicative Financial Risk"), (60, "Moderate Indicative Financial Risk"),
    (59.999, "Elevated Indicative Financial Risk"), (40, "Elevated Indicative Financial Risk"),
    (39.999, "High Indicative Financial Risk"), (0, "High Indicative Financial Risk"),
])
def test_risk_category_bands(total, label):
    assert cs.risk_category(total) == label


# ======================================================================================
# Healthy SYNTHETIC sample: pinned expected score
# ======================================================================================
class TestHealthySample:
    """make_sample_financials() FY2024 (millions):
    liquidity     4_800 / 2_600 = 1.846x               -> 75%  x 20 = 15
    leverage      D/E (400 + 2_800) / 5_400 = 0.593x   -> 75%
                  ND/EBITDA (3_200 - 1_500) / 1_800 = 0.944x -> 100%
                  average (0.75 + 1.0) / 2 = 0.875     -> 0.875 x 25 = 21.875
    profitability 1_350 / 9_000 = 0.15 exactly (ON the 15% boundary) -> 100% x 20 = 20
    coverage      1_350 / 150 = 9.0x                   -> 100% x 20 = 20
    cash flow     (1_500 - 600) / 9_000 = 0.10 exactly (ON the 10% boundary) -> 100% x 15 = 15
    total         15 + 21.875 + 20 + 20 + 15 = 91.875 -> Lower Indicative Financial Risk
    """

    @pytest.fixture
    def s(self) -> CreditScore:
        return score(make_sample_financials())

    def test_factor_points(self, s):
        assert [(fs.factor, fs.points, fs.max_points) for fs in s.factors] == [
            ("liquidity", 15.0, 20), ("leverage", 21.875, 25), ("profitability", 20.0, 20),
            ("coverage", 20.0, 20), ("cash_flow", 15.0, 15)]

    def test_total_and_category(self, s):
        assert s.sufficient_data is True
        assert s.total == 91.875
        assert s.category == "Lower Indicative Financial Risk"

    def test_total_equals_sum_of_factors(self, s):
        assert s.total == sum(fs.points for fs in s.factors)

    def test_operating_margin_exactly_on_15_percent_boundary_gets_full_points(self, s):
        assert factor(s, "profitability").points == 20.0
        assert "at or above 15%" in factor(s, "profitability").explanation

    def test_fcf_margin_exactly_on_10_percent_boundary_gets_full_points(self, s):
        assert factor(s, "cash_flow").points == 15.0
        assert "at or above 10%" in factor(s, "cash_flow").explanation

    def test_ratios_used_and_explanations(self, s):
        assert factor(s, "leverage").ratios_used == ["debt_to_equity", "net_debt_to_ebitda"]
        assert "21.875 of 25 points" in factor(s, "leverage").explanation
        assert config.SCORE_DISCLAIMER in s.explanation

    def test_uses_latest_year_only(self):
        # Changing an OLDER year must not change the score.
        f = make_sample_financials()
        f.periods[2].current_assets = FinancialValue(value=1.0)
        assert score(f).total == 91.875


# ======================================================================================
# Insufficient data
# ======================================================================================
class TestIncompleteSample:
    """make_incomplete_financials() FY2024 (millions):
    liquidity     900 / 1_100 = 0.818x -> >= 0.8 -> 25% x 20 = 5
    leverage      equity -500 -> 0 (real weakness) although D/E is UNAVAILABLE
    profitability 120 / 2_000 = 6%    -> >= 3% -> 50% x 20 = 10
    coverage      interest expense missing -> None
    cash flow     operating cash flow and capex missing -> None
    """

    @pytest.fixture
    def s(self) -> CreditScore:
        return score(make_incomplete_financials())

    def test_partial_factors(self, s):
        assert [fs.points for fs in s.factors] == [5.0, 0.0, 10.0, None, None]

    def test_total_and_category_are_none(self, s):
        assert s.sufficient_data is False
        assert s.total is None
        assert s.category is None

    def test_explanation_starts_with_label_and_lists_missing(self, s):
        assert s.explanation.startswith(config.INSUFFICIENT_SCORE_LABEL)
        assert "Coverage:" in s.explanation and "Cash flow:" in s.explanation
        assert "Interest expense is missing" in s.explanation

    def test_negative_equity_gets_zero_even_though_debt_to_equity_unavailable(self, s):
        lev = factor(s, "leverage")
        assert lev.points == 0.0
        assert "negative" in lev.explanation and "not missing data" in lev.explanation


def test_one_missing_factor_blocks_total_no_redistribution():
    # Current assets missing -> liquidity None; other four still scored (21.875+20+20+15)
    s = score(company(current_assets=None))
    assert factor(s, "liquidity").points is None
    assert [fs.points for fs in s.factors][1:] == [21.875, 20.0, 20.0, 15.0]
    assert s.total is None and s.sufficient_data is False


def test_empty_company_is_insufficient():
    f = CompanyFinancials(company=CompanyInfo(name="Empty (SYNTHETIC)"),
                          source_type=SourceType.SYNTHETIC)
    s = cs.compute_credit_score({}, f)
    assert s.sufficient_data is False and s.total is None and s.factors == []
    assert s.explanation.startswith(config.INSUFFICIENT_SCORE_LABEL)


def test_financial_institution_not_supported():
    s = score(company(fi=True))
    assert s.sufficient_data is False
    assert s.total is None and s.category is None
    assert s.explanation == config.FINANCIAL_INSTITUTION_MESSAGE
    assert len(s.factors) == 5  # still shown for transparency


# ======================================================================================
# Leverage special rules
# ======================================================================================
def test_negative_equity_with_everything_else_healthy():
    # Equity -1: leverage 0 -> 15 + 0 + 20 + 20 + 15 = 70 -> Moderate
    s = score(company(total_equity=-1))
    assert factor(s, "leverage").points == 0.0
    assert s.total == 70.0
    assert s.category == "Moderate Indicative Financial Risk"


def test_zero_equity_gets_zero_leverage_points():
    s = score(company(total_equity=0))
    assert factor(s, "leverage").points == 0.0
    assert "zero" in factor(s, "leverage").explanation


def test_negative_ebitda_with_positive_net_debt_scores_zero_component():
    # EBITDA -100 -> ND/EBITDA UNDEFINED; net debt 3_200 - 1_500 = 1_700 > 0 -> component 0
    # D/E 3_200 / 5_400 = 0.593x -> 75%. Average (0.75 + 0) / 2 = 0.375 x 25 = 9.375
    s = score(company(ebitda=-100))
    lev = factor(s, "leverage")
    assert lev.points == 9.375
    assert "EBITDA is not positive" in lev.explanation
    assert s.total == 15 + 9.375 + 20 + 20 + 15  # = 79.375


def test_zero_ebitda_with_positive_net_debt_scores_zero_component():
    s = score(company(ebitda=0))
    assert factor(s, "leverage").points == 9.375  # same arithmetic as above


def test_negative_ebitda_with_net_cash_uses_debt_to_equity_only():
    # Cash 4_000 > debt 3_200 -> net cash; EBITDA -100 -> ND/EBITDA not used.
    # D/E 0.593x -> 75% x 25 = 18.75
    lev = factor(score(company(ebitda=-100, cash=4_000)), "leverage")
    assert lev.points == 18.75
    assert "net cash" in lev.explanation


def test_net_debt_to_ebitda_unavailable_uses_debt_to_equity_only():
    # EBITDA and D&A missing -> ND/EBITDA UNAVAILABLE -> D/E only: 75% x 25 = 18.75
    lev = factor(score(company(ebitda=None, depreciation_amortization=None)), "leverage")
    assert lev.points == 18.75
    assert "only one leverage ratio usable" in lev.explanation.lower()


def test_net_cash_gets_full_net_debt_component():
    # Cash 4_000 -> ND = -800; ND/EBITDA = -800 / 1_800 = -0.44x -> 100%
    # D/E 75% -> average 0.875 x 25 = 21.875
    assert factor(score(company(cash=4_000)), "leverage").points == 21.875


def test_both_leverage_ratios_unavailable_is_none():
    # Short-term debt missing -> total debt unknown -> both ratios UNAVAILABLE
    s = score(company(short_term_debt=None))
    assert factor(s, "leverage").points is None
    assert s.total is None


# ======================================================================================
# Coverage special rules
# ======================================================================================
def test_zero_interest_with_net_cash_gets_full_coverage():
    # Interest 0; cash 4_000 - debt 3_200 = net debt -800 <= 0 -> 20 of 20
    cov = factor(score(company(interest_expense=0, cash=4_000)), "coverage")
    assert cov.points == 20.0
    assert cov.ratios_used == ["interest_coverage", "net_debt"]
    assert "no debt to service" in cov.explanation


def test_zero_interest_with_zero_net_debt_gets_full_coverage():
    # Cash 3_200 = debt 3_200 -> net debt 0 (<= 0) -> full
    assert factor(score(company(interest_expense=0, cash=3_200)), "coverage").points == 20.0


def test_zero_interest_with_positive_net_debt_is_none():
    # Interest 0 but net debt 1_700 > 0 -> cannot be scored
    s = score(company(interest_expense=0))
    assert factor(s, "coverage").points is None
    assert s.total is None


def test_zero_interest_with_unknown_net_debt_is_none():
    s = score(company(interest_expense=0, cash=None))
    assert factor(s, "coverage").points is None


def test_negative_ebit_coverage_scores_zero():
    # EBIT -150 / 150 = -1.0x -> below 1x -> 0
    assert factor(score(company(ebit=-150)), "coverage").points == 0.0
