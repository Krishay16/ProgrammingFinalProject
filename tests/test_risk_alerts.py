"""Tests for src/risk_alerts.py. Owned by Person 4.

Each alert is tested ON its trigger (must NOT fire: comparisons are strict) and just past it
(must fire), plus every severity boundary. Expected ratios are hand-calculated in comments.
Test periods use plain round numbers; HEALTHY is the SYNTHETIC make_sample_financials()
FY2024 period in millions.
"""
from __future__ import annotations

from typing import Optional

import pytest

from src import risk_alerts as ra
from src.financial_calculations import compute_all_ratios
from src.models import (CompanyFinancials, CompanyInfo, FinancialPeriod, FinancialValue,
                        Provenance, RiskAlert, Severity, SourceType)
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials

LOW, MEDIUM, HIGH = Severity.LOW, Severity.MEDIUM, Severity.HIGH

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


def period(fiscal_year: int = 2024, **overrides: Optional[float]) -> FinancialPeriod:
    values = {**HEALTHY, **overrides}
    return FinancialPeriod(fiscal_year=fiscal_year,
                           **{k: FinancialValue(value=v) for k, v in values.items()})


def company(*periods: FinancialPeriod, fi: bool = False) -> CompanyFinancials:
    """SYNTHETIC company; periods must be given NEWEST FIRST."""
    return CompanyFinancials(
        company=CompanyInfo(name="Test Co (SYNTHETIC)", is_financial_institution=fi),
        source_type=SourceType.SYNTHETIC, periods=list(periods))


def alerts_for(f: CompanyFinancials) -> list[RiskAlert]:
    return ra.generate_alerts(compute_all_ratios(f), f)


def find(f: CompanyFinancials, indicator: str) -> Optional[RiskAlert]:
    """The single alert with this indicator, or None."""
    found = [a for a in alerts_for(f) if a.indicator == indicator]
    assert len(found) <= 1
    return found[0] if found else None


def one(**overrides: Optional[float]) -> CompanyFinancials:
    return company(period(**overrides))


# ======================================================================================
# Healthy sample: no alerts
# ======================================================================================
def test_healthy_sample_has_no_alerts():
    # CR 1.85x, D/E 0.59x, ND/EBITDA 0.94x, coverage 9x, op. margin 15%, FCF +900,
    # revenue growth +6.3% (2023) and +7.1% (2024), no key input missing
    assert alerts_for(make_sample_financials()) == []


# ======================================================================================
# Liquidity: current_ratio < 1.0
# ======================================================================================
def test_liquidity_does_not_fire_at_exactly_1():
    # 2_600 / 2_600 = 1.0x -> not < 1.0
    assert find(one(current_assets=2_600), "current_ratio") is None


@pytest.mark.parametrize("current_assets, severity", [
    # current liabilities = 10_000 in every row
    (9_999, LOW),     # 0.9999x
    (9_000, LOW),     # 0.90x   (on the medium boundary: not < 0.9 -> low)
    (8_999, MEDIUM),  # 0.8999x
    (7_500, MEDIUM),  # 0.75x   (on the high boundary: not < 0.75 -> medium)
    (7_499, HIGH),    # 0.7499x
])
def test_liquidity_fires_with_severity(current_assets, severity):
    a = find(one(current_assets=current_assets, current_liabilities=10_000), "current_ratio")
    assert a is not None and a.severity == severity
    assert a.alert_type == "liquidity"
    assert a.measured_value == pytest.approx(current_assets / 10_000)
    assert a.threshold == "< 1.0x"
    assert a.interpretation == ra.LIQUIDITY_TEXT


# ======================================================================================
# Leverage
# ======================================================================================
def test_debt_to_equity_does_not_fire_at_exactly_2():
    # (0 + 10_800) / 5_400 = 2.0x -> not > 2.0
    assert find(one(short_term_debt=0, long_term_debt=10_800), "debt_to_equity") is None


@pytest.mark.parametrize("debt, severity", [
    # equity = 1_000 in every row; debt = long-term only
    (2_001, LOW),     # 2.001x
    (3_000, LOW),     # 3.0x (not > 3.0)
    (3_001, MEDIUM),  # 3.001x
    (4_000, MEDIUM),  # 4.0x (not > 4.0)
    (4_001, HIGH),    # 4.001x
])
def test_debt_to_equity_fires_with_severity(debt, severity):
    a = find(one(short_term_debt=0, long_term_debt=debt, total_equity=1_000), "debt_to_equity")
    assert a is not None and a.severity == severity
    assert a.threshold == "> 2.0x"
    assert a.interpretation == ra.LEVERAGE_TEXT


def test_net_debt_to_ebitda_does_not_fire_at_exactly_3():
    # (0 + 3_000 - 0) / 1_000 = 3.0x -> not > 3.0
    f = one(short_term_debt=0, long_term_debt=3_000, cash=0, ebitda=1_000)
    assert find(f, "net_debt_to_ebitda") is None


@pytest.mark.parametrize("debt, severity", [
    # cash 0, EBITDA 1_000 -> ND/EBITDA = debt / 1_000
    (3_001, LOW), (4_000, LOW), (4_001, MEDIUM), (5_000, MEDIUM), (5_001, HIGH),
])
def test_net_debt_to_ebitda_fires_with_severity(debt, severity):
    f = one(short_term_debt=0, long_term_debt=debt, cash=0, ebitda=1_000)
    a = find(f, "net_debt_to_ebitda")
    assert a is not None and a.severity == severity
    assert a.threshold == "> 3.0x"
    assert a.interpretation == ra.LEVERAGE_TEXT


def test_negative_equity_fires_high():
    a = find(one(total_equity=-1), "total_equity")
    assert a is not None and a.severity == HIGH and a.alert_type == "leverage"
    assert a.measured_value == -1
    assert a.interpretation == ra.LEVERAGE_TEXT


def test_zero_equity_fires_high():
    a = find(one(total_equity=0), "total_equity")
    assert a is not None and a.severity == HIGH


def test_positive_equity_no_equity_alert():
    assert find(one(total_equity=1), "total_equity") is None


# ======================================================================================
# Coverage: interest_coverage < 2.0x
# ======================================================================================
def test_coverage_does_not_fire_at_exactly_2():
    # 200 / 100 = 2.0x -> not < 2.0
    assert find(one(ebit=200, interest_expense=100), "interest_coverage") is None


@pytest.mark.parametrize("ebit, severity", [
    # interest expense = 100 -> coverage = EBIT / 100
    (199, LOW), (150, LOW), (149, MEDIUM), (100, MEDIUM), (99, HIGH), (-50, HIGH),
])
def test_coverage_fires_with_severity(ebit, severity):
    a = find(one(ebit=ebit, interest_expense=100), "interest_coverage")
    assert a is not None and a.severity == severity
    assert a.threshold == "< 2.0x"
    assert a.interpretation == ra.COVERAGE_TEXT


def test_coverage_undefined_zero_interest_no_alert():
    assert find(one(interest_expense=0), "interest_coverage") is None


# ======================================================================================
# Profitability: operating_margin < 0
# ======================================================================================
def test_profitability_does_not_fire_at_exactly_zero():
    assert find(one(ebit=0, revenue=1_000), "operating_margin") is None


@pytest.mark.parametrize("ebit, severity", [
    # revenue = 1_000 -> margin = EBIT / 1_000
    (-1, LOW),       # -0.1%
    (-50, LOW),      # -5.0% (not < -5%)
    (-51, MEDIUM),   # -5.1%
    (-150, MEDIUM),  # -15.0% (not < -15%)
    (-151, HIGH),    # -15.1%
])
def test_profitability_fires_with_severity(ebit, severity):
    a = find(one(ebit=ebit, revenue=1_000), "operating_margin")
    assert a is not None and a.severity == severity
    assert a.threshold == "< 0%"
    assert a.interpretation == ra.PROFITABILITY_TEXT


# ======================================================================================
# Cash flow: free_cash_flow < 0
# ======================================================================================
def test_cash_flow_does_not_fire_at_exactly_zero():
    # 600 - 600 = 0 -> not < 0
    assert find(one(operating_cash_flow=600, capex=600), "free_cash_flow") is None


@pytest.mark.parametrize("capex, severity", [
    # OCF 0, revenue 1_000 -> FCF = -capex, FCF margin = -capex / 1_000
    (1, LOW),       # -0.1%
    (50, LOW),      # -5.0% (not < -5%)
    (51, MEDIUM),   # -5.1%
    (100, MEDIUM),  # -10.0% (not < -10%)
    (101, HIGH),    # -10.1%
])
def test_cash_flow_fires_with_severity(capex, severity):
    a = find(one(operating_cash_flow=0, capex=capex, revenue=1_000), "free_cash_flow")
    assert a is not None and a.severity == severity
    assert a.measured_value == -capex
    assert a.interpretation == ra.CASH_FLOW_TEXT


def test_cash_flow_severity_medium_when_margin_unavailable():
    a = find(one(operating_cash_flow=0, capex=500, revenue=None), "free_cash_flow")
    assert a is not None and a.severity == MEDIUM
    assert "FCF margin unavailable" in a.threshold


# ======================================================================================
# Trend: revenue fell in each of the last two comparable periods
# ======================================================================================
def three_years(r2024: float, r2023: float, r2022: float) -> CompanyFinancials:
    return company(period(2024, revenue=r2024), period(2023, revenue=r2023),
                   period(2022, revenue=r2022))


@pytest.mark.parametrize("revenues, severity", [
    # cumulative decline = 1 - revenue 2024 / revenue 2022
    ((980, 990, 1_000), LOW),     # 1 - 980/1000 = 2%
    ((940, 960, 1_000), MEDIUM),  # 1 - 940/1000 = 6%
    ((800, 900, 1_000), HIGH),    # 1 - 800/1000 = 20%
])
def test_trend_fires_with_severity(revenues, severity):
    a = find(three_years(*revenues), "revenue_growth")
    assert a is not None and a.severity == severity
    assert a.alert_type == "trend"
    assert a.interpretation == ra.TREND_TEXT
    # growth 2024 = 980/990 - 1 etc.
    assert a.measured_value == pytest.approx(revenues[0] / revenues[1] - 1)


def test_trend_does_not_fire_when_latest_growth_is_zero():
    # 2024 = 2023 -> growth exactly 0 -> not < 0
    assert find(three_years(900, 900, 1_000), "revenue_growth") is None


def test_trend_does_not_fire_when_only_latest_year_fell():
    assert find(three_years(900, 1_000, 950), "revenue_growth") is None


def test_trend_needs_two_comparable_growth_rates():
    # Only two periods -> one growth rate -> no trend alert
    f = company(period(2024, revenue=800), period(2023, revenue=900))
    assert find(f, "revenue_growth") is None


def test_trend_does_not_fire_across_a_gap_year():
    # 2024, 2023, 2021: FY2023 growth needs FY2022 -> UNAVAILABLE -> no alert
    f = company(period(2024, revenue=800), period(2023, revenue=900),
                period(2021, revenue=1_000))
    assert find(f, "revenue_growth") is None


# ======================================================================================
# Data quality
# ======================================================================================
def test_data_quality_one_missing_is_low():
    a = find(one(interest_expense=None), "key_inputs")
    assert a is not None and a.severity == LOW and a.measured_value == 1
    assert "Interest expense" in a.interpretation


@pytest.mark.parametrize("missing, severity", [
    (["capex"], LOW),
    (["capex", "cash"], MEDIUM),
    (["capex", "cash", "revenue"], MEDIUM),
    (["capex", "cash", "revenue", "ebit"], HIGH),
])
def test_data_quality_severity_by_count(missing, severity):
    a = find(one(**{m: None for m in missing}), "key_inputs")
    assert a.severity == severity and a.measured_value == len(missing)


def test_derivable_ebitda_is_not_counted_missing():
    # EBITDA missing but EBIT + D&A known -> derivable -> no data-quality alert
    assert find(one(ebitda=None), "key_inputs") is None


def test_underivable_ebitda_is_counted_missing():
    a = find(one(ebitda=None, depreciation_amortization=None), "key_inputs")
    assert a is not None and a.measured_value == 1


def test_non_key_field_missing_no_alert():
    assert find(one(financing_cash_flow=None), "key_inputs") is None


# ======================================================================================
# Incomplete SYNTHETIC sample: the three pinned alerts
# ======================================================================================
def test_incomplete_sample_alerts():
    """make_incomplete_financials() FY2024 (millions):
    liquidity    900 / 1_100 = 0.818x -> < 1.0 fires; 0.75 <= 0.818 < 0.9 -> MEDIUM
    leverage     equity -500 -> HIGH (D/E and ND/EBITDA are UNAVAILABLE: short-term debt
                 missing, so the equity check must work on total_equity directly)
    data quality short_term_debt, interest_expense, operating_cash_flow, capex = 4 -> HIGH
    No coverage / cash-flow alert (inputs missing), no profitability alert (120/2_000 = 6%).
    """
    alerts = alerts_for(make_incomplete_financials())
    assert [(a.alert_type, a.indicator, a.severity) for a in alerts] == [
        ("liquidity", "current_ratio", MEDIUM),
        ("leverage", "total_equity", HIGH),
        ("data_quality", "key_inputs", HIGH),
    ]
    assert alerts[0].measured_value == pytest.approx(900 / 1_100)
    assert alerts[1].measured_value == -500_000_000
    assert alerts[2].measured_value == 4
    for a in alerts:
        assert a.fiscal_year == 2024
        assert a.source_reference == "tests/fixtures/sample_data.py"


# ======================================================================================
# source_reference, financial institutions, wording
# ======================================================================================
def test_source_reference_from_provenance():
    p = period(current_assets=900, current_liabilities=1_000)
    p.current_assets.provenance = Provenance(
        source_type=SourceType.SEC_EDGAR, source_ref="https://example.invalid/companyfacts",
        tag="AssetsCurrent", location="10-K accn 0000000000-24-000001")
    p.current_liabilities.provenance = Provenance(
        source_type=SourceType.PDF, source_ref="report.pdf", location="page 12")
    a = find(company(p), "current_ratio")
    assert a.source_reference == (
        "AssetsCurrent | 10-K accn 0000000000-24-000001 | https://example.invalid/companyfacts"
        "; page 12 | report.pdf")


def test_source_reference_none_without_provenance():
    a = find(one(current_assets=900, current_liabilities=1_000), "current_ratio")
    assert a.source_reference is None


def test_financial_institution_only_gets_data_quality_alert():
    f = make_incomplete_financials()
    f.company.is_financial_institution = True
    alerts = alerts_for(f)
    assert [a.alert_type for a in alerts] == ["data_quality"]


def test_empty_company_has_no_alerts():
    assert alerts_for(company()) == []


def test_wording_never_mentions_default_or_distress():
    # Build many alerts at once: weak liquidity, high leverage, losses, negative FCF, decline
    weak = dict(current_assets=500, ebit=-500, operating_cash_flow=0, capex=500,
                long_term_debt=50_000, total_equity=-1, interest_expense=None)
    f = company(period(2024, revenue=800, **weak), period(2023, revenue=900),
                period(2022, revenue=1_000))
    alerts = alerts_for(f)
    assert len(alerts) >= 5
    for a in alerts:
        text = f"{a.title} {a.threshold} {a.interpretation}".lower()
        assert "default" not in text and "distress" not in text
