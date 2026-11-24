"""SYNTHETIC: invented for testing, not a real company.

Owned by Person 1. Everyone builds and tests against these two fixtures:
  make_sample_financials()      healthy company, 3 annual periods, all fields filled
  make_incomplete_financials()  one period with gaps and NEGATIVE equity

All numbers are written in MILLIONS below for readability and stored in full currency
units (x 1_000_000), as required by the shared conventions.
"""
from __future__ import annotations

from datetime import date

from src.models import (CompanyFinancials, CompanyInfo, FinancialPeriod, FinancialValue,
                        Provenance, SourceType, Units, ValueOrigin, VerificationStatus)

_MILLION = 1_000_000.0
_SOURCE_REF = "tests/fixtures/sample_data.py"


def _fv(millions: float | None) -> FinancialValue:
    """Wrap a value given in millions as a FinancialValue with SYNTHETIC provenance."""
    if millions is None:
        return FinancialValue()
    return FinancialValue(
        value=millions * _MILLION,
        provenance=Provenance(
            source_type=SourceType.SYNTHETIC,
            source_ref=_SOURCE_REF,
            origin=ValueOrigin.REPORTED,
            verification=VerificationStatus.UNVERIFIED,
            note="SYNTHETIC demo data",
        ),
    )


def _period(fiscal_year: int, values: dict[str, float | None]) -> FinancialPeriod:
    """Build a SYNTHETIC annual period from {field: value in millions}."""
    return FinancialPeriod(
        fiscal_year=fiscal_year,
        period_start=date(fiscal_year, 1, 1),
        period_end=date(fiscal_year, 12, 31),
        filing_date=date(fiscal_year + 1, 2, 15),
        form_type=None,
        is_annual=True,
        currency="USD",
        original_units=Units.MILLIONS,
        **{field: _fv(v) for field, v in values.items()},
    )


def make_sample_financials() -> CompanyFinancials:
    """SYNTHETIC healthy non-financial company, FY2024/2023/2022 (newest first)."""
    fy2024 = {
        # Balance sheet: 6_600 + 5_400 = 12_000
        "cash": 1_500, "current_assets": 4_800, "total_assets": 12_000,
        "current_liabilities": 2_600, "total_liabilities": 6_600,
        "short_term_debt": 400, "long_term_debt": 2_800, "total_equity": 5_400,
        # Income statement: 9_000 - 5_850 = 3_150 ; EBITDA = 1_350 + 450
        "revenue": 9_000, "cost_of_revenue": 5_850, "gross_profit": 3_150,
        "ebit": 1_350, "ebitda": 1_800, "interest_expense": 150,
        "net_income": 900, "depreciation_amortization": 450,
        # Cash flow
        "operating_cash_flow": 1_500, "capex": 600,
        "investing_cash_flow": -750, "financing_cash_flow": -500,
    }
    fy2023 = {
        # 6_400 + 5_000 = 11_400
        "cash": 1_300, "current_assets": 4_500, "total_assets": 11_400,
        "current_liabilities": 2_500, "total_liabilities": 6_400,
        "short_term_debt": 450, "long_term_debt": 2_900, "total_equity": 5_000,
        # 8_400 - 5_500 = 2_900 ; EBITDA = 1_200 + 430
        "revenue": 8_400, "cost_of_revenue": 5_500, "gross_profit": 2_900,
        "ebit": 1_200, "ebitda": 1_630, "interest_expense": 160,
        "net_income": 780, "depreciation_amortization": 430,
        "operating_cash_flow": 1_300, "capex": 550,
        "investing_cash_flow": -700, "financing_cash_flow": -450,
    }
    fy2022 = {
        # 6_300 + 4_500 = 10_800
        "cash": 1_100, "current_assets": 4_200, "total_assets": 10_800,
        "current_liabilities": 2_400, "total_liabilities": 6_300,
        "short_term_debt": 500, "long_term_debt": 3_000, "total_equity": 4_500,
        # 7_900 - 5_200 = 2_700 ; EBITDA = 1_050 + 410
        "revenue": 7_900, "cost_of_revenue": 5_200, "gross_profit": 2_700,
        "ebit": 1_050, "ebitda": 1_460, "interest_expense": 170,
        "net_income": 680, "depreciation_amortization": 410,
        "operating_cash_flow": 1_150, "capex": 500,
        "investing_cash_flow": -620, "financing_cash_flow": -400,
    }
    return CompanyFinancials(
        company=CompanyInfo(name="Sample Manufacturing Co (SYNTHETIC)", ticker="SYNTH",
                            country="n/a", reporting_framework="SYNTHETIC"),
        source_type=SourceType.SYNTHETIC,
        periods=[_period(2024, fy2024), _period(2023, fy2023), _period(2022, fy2022)],
        warnings=["SYNTHETIC demo data: not a real company."],
    )


def make_incomplete_financials() -> CompanyFinancials:
    """SYNTHETIC company, one period: gaps (None) and NEGATIVE equity.

    Missing on purpose: interest_expense, short_term_debt, and all four cash-flow fields.
    """
    fy2024 = {
        # Balance sheet: 3_500 + (-500) = 3_000 -> negative equity
        "cash": 150, "current_assets": 900, "total_assets": 3_000,
        "current_liabilities": 1_100, "total_liabilities": 3_500,
        "short_term_debt": None, "long_term_debt": 1_800, "total_equity": -500,
        # 2_000 - 1_500 = 500 ; EBITDA = 120 + 80
        "revenue": 2_000, "cost_of_revenue": 1_500, "gross_profit": 500,
        "ebit": 120, "ebitda": 200, "interest_expense": None,
        "net_income": -60, "depreciation_amortization": 80,
        "operating_cash_flow": None, "capex": None,
        "investing_cash_flow": None, "financing_cash_flow": None,
    }
    return CompanyFinancials(
        company=CompanyInfo(name="Incomplete Holdings (SYNTHETIC)", ticker="SYNTH2",
                            country="n/a", reporting_framework="SYNTHETIC"),
        source_type=SourceType.SYNTHETIC,
        periods=[_period(2024, fy2024)],
        warnings=["SYNTHETIC demo data: not a real company."],
    )
