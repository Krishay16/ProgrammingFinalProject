"""Offline tests for src/financial_normalizer.py (Person 2).

Fixtures in tests/fixtures/sec/:
* microsoft_companyfacts_trimmed_fixture.json: REAL SEC data (Microsoft, June year end),
  trimmed by scripts/build_sec_fixtures.py from the cached companyfacts response. Expected
  values below were read from that fixture, not typed from memory.
* SYNTHETIC_*_trimmed_fixture.json: invented values for edge cases (not real companies).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src import financial_normalizer as fn
from src.financial_normalizer import normalize_company_facts
from src.models import (
    ALL_FIELDS,
    CompanyFinancials,
    CompanyInfo,
    SourceType,
    Units,
    ValueOrigin,
    VerificationStatus,
)

SEC_DIR = Path(__file__).parent / "fixtures" / "sec"
MSFT_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"


def load(name: str) -> dict:
    with open(SEC_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def synthetic(name: str, max_periods: int = 3) -> CompanyFinancials:
    facts = load(f"SYNTHETIC_{name}_trimmed_fixture.json")
    company = CompanyInfo(name=facts["entityName"], cik=str(facts["cik"]))
    return normalize_company_facts(facts, company, max_periods=max_periods)


def warnings_text(f: CompanyFinancials) -> str:
    return "\n".join(f.warnings)


@pytest.fixture(scope="module")
def msft() -> CompanyFinancials:
    facts = load("microsoft_companyfacts_trimmed_fixture.json")
    return normalize_company_facts(facts, CompanyInfo(name="MICROSOFT CORP", ticker="MSFT",
                                                      cik="0000789019"))


# --------------------------------------------------------------------------- Microsoft (REAL)

def test_msft_june_fiscal_year_end_newest_first(msft):
    assert msft.source_type == SourceType.SEC_EDGAR
    assert [p.fiscal_year for p in msft.periods] == [2026, 2025, 2024]
    assert [p.period_end for p in msft.periods] == [
        date(2026, 6, 30), date(2025, 6, 30), date(2024, 6, 30)]
    assert [p.period_start for p in msft.periods] == [
        date(2025, 7, 1), date(2024, 7, 1), date(2023, 7, 1)]
    for p in msft.periods:
        assert p.currency == "USD"
        assert p.original_units == Units.UNITS
        assert p.is_annual


def test_msft_prior_year_values_come_from_end_date_not_fy(msft):
    # Every 10-K repeats prior years with the FILING's fy; values must differ per end date.
    fy24 = msft.period(2024)
    assert fy24.get("net_income") == 88_136_000_000.0
    assert msft.period(2025).get("net_income") == 101_832_000_000.0
    assert msft.period(2026).get("net_income") == 133_749_000_000.0


def test_msft_quarterly_and_proxy_rows_ignored(msft):
    # The fixture contains a DEF 14A row (fp=None) and 10-Q rows for NetIncomeLoss/Assets.
    facts = load("microsoft_companyfacts_trimmed_fixture.json")
    rows = facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]
    assert any(r["form"] == "10-Q" for r in rows)
    assert any(r["form"] == "DEF 14A" for r in rows)
    for p in msft.periods:
        assert p.net_income.provenance.location.startswith("10-K accn ")


def test_msft_interest_uses_one_tag_for_all_years(msft):
    tags = {p.interest_expense.provenance.tag for p in msft.periods}
    assert tags == {"InterestExpenseNonoperating"}
    assert "Interest expense" not in warnings_text(msft)


def test_msft_da_missing_and_ebitda_left_none(msft):
    for p in msft.periods:
        assert p.get("depreciation_amortization") is None
        assert p.get("ebitda") is None
    assert "Depreciation and amortization" in warnings_text(msft)
    assert "EBITDA" not in warnings_text(msft)


def test_msft_short_term_debt_derived_from_components(msft):
    fy25 = msft.period(2025).short_term_debt
    assert fy25.provenance.origin == ValueOrigin.DERIVED
    assert fy25.provenance.tag == "LongTermDebtCurrent + CommercialPaper"
    assert "LongTermDebtCurrent" in fy25.provenance.note
    assert "CommercialPaper" in fy25.provenance.note
    # CommercialPaper is not reported for FY2026 -> only the component present is used.
    assert msft.period(2026).short_term_debt.provenance.tag == "LongTermDebtCurrent"
    assert "Short-term debt" in warnings_text(msft)


def test_msft_provenance(msft):
    p = msft.latest()
    prov = p.revenue.provenance
    assert prov.source_type == SourceType.SEC_EDGAR
    assert prov.source_ref == MSFT_URL
    assert prov.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert prov.verification == VerificationStatus.SOURCE_STRUCTURED
    assert prov.origin == ValueOrigin.REPORTED
    assert prov.location.startswith("10-K accn ")
    assert prov.filing_date == p.filing_date
    assert p.form_type == "10-K"


def test_msft_capex_positive(msft):
    for p in msft.periods:
        assert p.get("capex") > 0


def test_msft_reporting_framework_set(msft):
    assert msft.company.reporting_framework == "US GAAP"
    assert msft.company.ticker == "MSFT"


def test_msft_max_periods(msft):
    facts = load("microsoft_companyfacts_trimmed_fixture.json")
    company = CompanyInfo(name="MICROSOFT CORP", cik="789019")
    four = normalize_company_facts(facts, company, max_periods=4)
    assert [p.fiscal_year for p in four.periods] == [2026, 2025, 2024, 2023]
    one = normalize_company_facts(facts, company, max_periods=1)
    assert [p.fiscal_year for p in one.periods] == [2026]
    assert four.periods[0].revenue.provenance.source_ref == MSFT_URL  # CIK padded


# --------------------------------------------------------------------------- duplicates / noise

def test_amendment_10ka_wins_over_original():
    f = synthetic("duplicates_quarterly", max_periods=4)
    ni = f.period(2021).net_income
    assert ni.value == 65
    assert ni.provenance.location == "10-K/A accn 0000000001-22-000020"
    assert ni.provenance.filing_date == date(2022, 8, 1)


def test_later_10k_restatement_wins_and_prior_year_assigned_by_end():
    f = synthetic("duplicates_quarterly")
    fy22 = f.period(2022)
    assert fy22.get("net_income") == 85          # restated in the FY2023 10-K
    assert fy22.get("total_assets") == 4850
    assert fy22.net_income.provenance.location == "10-K accn 0000000001-24-000010"
    # Period metadata = most recent filing that reported the period.
    assert fy22.filing_date == date(2024, 2, 15)
    assert fy22.form_type == "10-K"


def test_tie_on_filed_date_highest_accn_wins():
    f = synthetic("duplicates_quarterly")
    rev = f.period(2023).revenue
    assert rev.value == 1010
    assert rev.provenance.location == "10-K accn 0000000001-24-000011"


def test_quarterly_and_short_fy_facts_ignored():
    f = synthetic("duplicates_quarterly")
    assert [p.fiscal_year for p in f.periods] == [2023, 2022, 2021]
    assert [p.period_end for p in f.periods] == [
        date(2023, 12, 31), date(2022, 12, 31), date(2021, 12, 31)]
    # Not the 10-Q (30), not the 91-day fp=FY row filed later (25), not the proxy (999).
    assert f.period(2023).get("net_income") == 100
    assert f.period(2023).get("total_assets") == 5000


def test_missing_tag_is_none_not_zero_with_warning():
    f = synthetic("duplicates_quarterly")
    p = f.latest()
    for field in ("cash", "ebit", "operating_cash_flow", "capex", "short_term_debt"):
        assert p.get(field) is None
        assert getattr(p, field).provenance is None
    assert "FY2023: not found in the SEC data (left blank, not zero)" in warnings_text(f)
    assert "Operating income (EBIT)" in warnings_text(f)


def test_default_max_periods_is_three():
    assert len(synthetic("duplicates_quarterly").periods) == 3
    assert len(synthetic("duplicates_quarterly", max_periods=4).periods) == 4


# --------------------------------------------------------------------------- tag consistency

def test_tag_switch_per_period_with_warning():
    f = synthetic("tag_switch")
    tags = {p.fiscal_year: p.revenue.provenance.tag for p in f.periods}
    assert tags == {2023: "RevenueFromContractWithCustomerExcludingAssessedTax",
                    2022: "RevenueFromContractWithCustomerExcludingAssessedTax",
                    2021: "SalesRevenueNet"}
    assert f.period(2021).get("revenue") == 800
    text = warnings_text(f)
    assert "Revenue: the SEC tag used differs between periods" in text
    assert "FY2021: SalesRevenueNet" in text


def test_single_tag_covering_all_periods_is_preferred():
    f = synthetic("tag_switch")
    # InterestExpense has higher priority but exists only for FY2023;
    # InterestExpenseNonoperating covers all years and is used for all of them.
    assert {p.interest_expense.provenance.tag for p in f.periods} == {
        "InterestExpenseNonoperating"}
    assert f.period(2023).get("interest_expense") == 12
    assert "Interest expense" not in warnings_text(f)


# --------------------------------------------------------------------------- debt / signs

@pytest.fixture(scope="module")
def debt() -> CompanyFinancials:
    return synthetic("debt_fallbacks")


def test_debt_current_present_no_double_counting(debt):
    std = debt.period(2023).short_term_debt
    assert std.value == 500  # NOT 500 + 300 + 200
    assert std.provenance.tag == "DebtCurrent"
    assert std.provenance.origin == ValueOrigin.REPORTED


def test_short_term_debt_derived_from_present_components_only(debt):
    std = debt.period(2022).short_term_debt
    assert std.value == 350  # LongTermDebtCurrent 250 + ShortTermBorrowings 100
    assert std.provenance.origin == ValueOrigin.DERIVED
    assert std.provenance.verification == VerificationStatus.SOURCE_STRUCTURED
    assert std.provenance.tag == "LongTermDebtCurrent + ShortTermBorrowings"
    assert "CommercialPaper" not in std.provenance.tag
    assert "LongTermDebtCurrent" in std.provenance.note
    assert "ShortTermBorrowings" in std.provenance.note


def test_short_term_debt_none_without_components(debt):
    assert debt.period(2021).get("short_term_debt") is None


def test_long_term_debt_reported_then_derived_then_none(debt):
    assert debt.period(2023).get("long_term_debt") == 2000
    ltd22 = debt.period(2022).long_term_debt
    assert ltd22.value == 2050  # LongTermDebt 2300 - LongTermDebtCurrent 250
    assert ltd22.provenance.origin == ValueOrigin.DERIVED
    assert ltd22.provenance.tag == "LongTermDebt - LongTermDebtCurrent"
    # FY2021 has LongTermDebt but no LongTermDebtCurrent -> must stay None.
    assert debt.period(2021).get("long_term_debt") is None


def test_negative_capex_and_interest_stored_positive_with_note(debt):
    p = debt.period(2023)
    assert p.get("capex") == 150
    assert p.get("interest_expense") == 40
    assert "sign flipped" in p.capex.provenance.note
    assert "sign flipped" in p.interest_expense.provenance.note
    assert p.capex.provenance.original_text == "-150"
    assert debt.period(2022).get("capex") == 140
    assert debt.period(2022).capex.provenance.note is None


def test_total_liabilities_derived_prefers_equity_including_nci(debt):
    tl23 = debt.period(2023).total_liabilities
    assert tl23.value == 6000 - 2500
    assert tl23.provenance.origin == ValueOrigin.DERIVED
    assert "NoncontrollingInterest" in tl23.provenance.tag
    tl22 = debt.period(2022).total_liabilities
    assert tl22.value == 5500 - 2300
    assert "may include non-controlling interest" in tl22.provenance.note


def test_restricted_cash_fallback_has_note(debt):
    assert debt.period(2023).cash.provenance.tag == "CashAndCashEquivalentsAtCarryingValue"
    cash22 = debt.period(2022).cash
    assert cash22.value == 380
    assert "restricted cash" in cash22.provenance.note


def test_ebitda_always_none(debt):
    assert all(p.get("ebitda") is None for p in debt.periods)


# --------------------------------------------------------------------------- FY collision / 52-53 weeks

def test_fiscal_year_collision_keeps_later_end():
    f = synthetic("fy_collision")
    assert [p.fiscal_year for p in f.periods] == [2023, 2022, 2020]
    assert f.period(2023).period_end == date(2023, 12, 31)
    text = warnings_text(f)
    assert "2023-01-01" in text and "2023-12-31" in text
    assert "Kept the later one (2023-12-31)" in text


def test_53_week_year_accepted():
    f = synthetic("fy_collision")
    p22 = f.period(2022)
    assert (p22.period_end - p22.period_start).days == 371
    assert p22.get("net_income") == 20


@pytest.mark.parametrize("days, accepted", [
    (90, False), (349, False), (350, True), (364, True), (371, True), (380, True), (381, False)])
def test_annual_duration_window(days, accepted):
    end = date(2024, 12, 31)
    start = date.fromordinal(end.toordinal() - days)
    assert fn._is_annual_duration(start, end) is accepted


# --------------------------------------------------------------------------- currency

def test_non_usd_currency_kept_and_never_mixed():
    f = synthetic("non_usd")
    assert [p.currency for p in f.periods] == ["EUR", "EUR", "EUR"]
    p = f.period(2023)
    assert p.get("net_income") == 50  # EUR value, not the EUR/shares unit
    assert p.get("cash") == 300       # EUR, not the USD 330
    assert p.get("long_term_debt") is None  # only reported in USD -> not mixed
    assert "only in USD, but this period is in EUR" in warnings_text(f)


# --------------------------------------------------------------------------- no data

@pytest.mark.parametrize("facts", [
    {},
    {"cik": 1, "facts": {}},
    {"cik": 1, "facts": {"us-gaap": {}}},
    {"cik": 1, "facts": {"dei": {"EntityCommonStockSharesOutstanding": {}}}},
    {"cik": 1, "facts": {"us-gaap": "garbage"}},
])
def test_no_us_gaap_returns_empty_with_warning(facts):
    f = normalize_company_facts(facts, CompanyInfo(name="SYNTHETIC Empty"))
    assert f.periods == []
    assert f.source_type == SourceType.SEC_EDGAR
    assert f.warnings and "US GAAP" in f.warnings[0]


def test_ifrs_filer_gets_specific_warning():
    facts = {"cik": 1, "facts": {"ifrs-full": {"Revenue": {"units": {"EUR": []}}}}}
    f = normalize_company_facts(facts, CompanyInfo(name="SYNTHETIC IFRS SA"))
    assert f.periods == []
    assert "IFRS" in f.warnings[0]


def test_only_quarterly_data_returns_empty_with_warning():
    q = {"start": "2024-01-01", "end": "2024-03-31", "val": 5, "accn": "0000000009-24-000001",
         "fy": 2024, "fp": "Q1", "form": "10-Q", "filed": "2024-05-01"}
    facts = {"cik": 9, "facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [q]}}}}}
    f = normalize_company_facts(facts, CompanyInfo(name="SYNTHETIC Quarterly Only"))
    assert f.periods == []
    assert "No annual 10-K financial statements" in f.warnings[0]


def test_malformed_fact_rows_are_skipped_not_raised():
    good = {"start": "2023-01-01", "end": "2023-12-31", "val": 7, "accn": "0000000009-24-1",
            "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-02-01"}
    bad_rows = [None, "x", {**good, "val": "abc"}, {**good, "val": True},
                {**good, "end": "not-a-date"}, {**good, "filed": None}]
    assets = {"end": "2023-12-31", "val": 70, "accn": "0000000009-24-1", "fy": 2023,
              "fp": "FY", "form": "10-K", "filed": "2024-02-01"}
    facts = {"cik": 9, "facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": bad_rows + [good]}},
        "Assets": {"units": {"USD": [assets]}},
        "Revenues": "not-a-dict",
    }}}
    f = normalize_company_facts(facts, CompanyInfo(name="SYNTHETIC Malformed"))
    assert [p.fiscal_year for p in f.periods] == [2023]
    assert f.latest().get("net_income") == 7


def test_missing_cik_does_not_crash():
    facts = load("SYNTHETIC_tag_switch_trimmed_fixture.json")
    facts = {k: v for k, v in facts.items() if k != "cik"}
    f = normalize_company_facts(facts, CompanyInfo(name="SYNTHETIC No CIK"))
    assert f.latest().revenue.provenance.source_ref == "SEC EDGAR companyfacts (CIK unknown)"


def test_every_field_present_on_every_period(msft):
    for p in msft.periods:
        for field in ALL_FIELDS:
            assert hasattr(p, field)
