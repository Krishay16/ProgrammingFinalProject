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


# --------------------------------------------------------------------------- review follow-ups
# Inline SYNTHETIC companyfacts (invented values, not a real company). Years end 31 Dec.

def inline_facts(tags: dict[str, dict[int, float]],
                 currency_by_year: dict[int, str] | None = None) -> dict:
    """Build a minimal companyfacts dict: {tag: {year: value}}, one 10-K per year."""
    currency_by_year = currency_by_year or {}
    us_gaap: dict = {}
    for tag, by_year in tags.items():
        units: dict[str, list] = {}
        for year, val in by_year.items():
            accn = f"0000000099-{(year + 1) % 100:02d}-000001"
            row = {"end": f"{year}-12-31", "val": val, "accn": accn, "fy": year, "fp": "FY",
                   "form": "10-K", "filed": f"{year + 1}-02-15"}
            if tag in fn.FLOW_TAGS:
                row["start"] = f"{year}-01-01"
            units.setdefault(currency_by_year.get(year, "USD"), []).append(row)
        us_gaap[tag] = {"units": units}
    return {"cik": 99, "entityName": "SYNTHETIC INLINE CO", "facts": {"us-gaap": us_gaap}}


CORE = {"NetIncomeLoss": {2022: 10, 2023: 11, 2024: 12},
        "Assets": {2022: 100, 2023: 110, 2024: 120}}


def normalize_inline(tags: dict, **kw) -> CompanyFinancials:
    return normalize_company_facts(inline_facts({**CORE, **tags}, **kw),
                                   CompanyInfo(name="SYNTHETIC INLINE CO", cik="99"))


# 1. Short-term debt from incomplete components

MSFT_STD_WARNING = (
    "Short-term debt is the sum of the reported components only ("
    "FY2026: LongTermDebtCurrent only, CommercialPaper and ShortTermBorrowings not reported; "
    "FY2025: LongTermDebtCurrent and CommercialPaper only, ShortTermBorrowings not reported; "
    "FY2024: LongTermDebtCurrent and CommercialPaper only, ShortTermBorrowings not reported). "
    "If the company has the missing items, short-term debt and leverage ratios may be "
    "understated.")


def test_msft_incomplete_short_term_debt_one_combined_warning(msft):
    assert MSFT_STD_WARNING in msft.warnings
    assert sum("Short-term debt is the sum" in w for w in msft.warnings) == 1
    note = msft.period(2026).short_term_debt.provenance.note
    assert "Not reported (so not included): CommercialPaper, ShortTermBorrowings." in note
    assert "DebtCurrent not reported" in note


def test_incomplete_short_term_debt_warning_and_note_synthetic(debt):
    # FY2022: LongTermDebtCurrent 250 + ShortTermBorrowings 100, no CommercialPaper.
    std = debt.period(2022).short_term_debt
    assert std.value == 350
    assert "Not reported (so not included): CommercialPaper." in std.provenance.note
    # FY2023 uses reported DebtCurrent and FY2021 has no short-term debt -> only FY2022 listed.
    assert ("Short-term debt is the sum of the reported components only (FY2022: "
            "LongTermDebtCurrent and ShortTermBorrowings only, CommercialPaper not reported). "
            "If the company has the missing items, short-term debt and leverage ratios may be "
            "understated.") in debt.warnings


def test_complete_short_term_debt_components_no_warning():
    f = normalize_inline({"LongTermDebtCurrent": {2022: 1, 2023: 2, 2024: 3},
                          "CommercialPaper": {2022: 10, 2023: 20, 2024: 30},
                          "ShortTermBorrowings": {2022: 100, 2023: 200, 2024: 300}})
    std = f.period(2024).short_term_debt
    assert std.value == 333
    assert std.provenance.tag == "LongTermDebtCurrent + CommercialPaper + ShortTermBorrowings"
    assert "Not reported" not in std.provenance.note
    assert "Short-term debt is the sum" not in warnings_text(f)


# 2. Restricted cash is a per-period gap filler only

RESTRICTED = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
CLEAN = "CashAndCashEquivalentsAtCarryingValue"


def test_clean_cash_2_of_3_years_restricted_all_3_years():
    f = normalize_inline({CLEAN: {2023: 50, 2024: 60},
                          RESTRICTED: {2022: 45, 2023: 55, 2024: 65}})
    # Clean tag used wherever it exists; restricted only fills the FY2022 gap.
    assert {p.fiscal_year: (p.get("cash"), p.cash.provenance.tag) for p in f.periods} == {
        2024: (60, CLEAN), 2023: (50, CLEAN), 2022: (45, RESTRICTED)}
    assert f.period(2024).cash.provenance.note is None
    assert f.period(2023).cash.provenance.note is None
    assert "restricted cash" in f.period(2022).cash.provenance.note
    assert ("FY2022: cash includes restricted cash (CashAndCashEquivalentsAtCarryingValue not "
            "reported), which may not be available to repay debt, so liquidity ratios may be "
            "overstated.") in f.warnings
    restricted_warnings = [w for w in f.warnings if "cash includes restricted cash" in w]
    assert len(restricted_warnings) == 1
    text = warnings_text(f)
    assert "Cash and cash equivalents: the SEC tag used differs between periods" in text
    assert f"FY2024: {CLEAN}; FY2023: {CLEAN}; FY2022: {RESTRICTED}" in text


def test_restricted_cash_only_used_everywhere_with_warning_per_year():
    f = normalize_inline({RESTRICTED: {2022: 45, 2023: 55, 2024: 65}})
    assert {p.cash.provenance.tag for p in f.periods} == {RESTRICTED}
    assert [p.get("cash") for p in f.periods] == [65, 55, 45]
    for year in (2022, 2023, 2024):
        assert f"FY{year}: cash includes restricted cash" in warnings_text(f)
    assert "the SEC tag used differs" not in warnings_text(f)  # one tag for all years


def test_clean_cash_all_years_no_restricted_warning():
    f = normalize_inline({CLEAN: {2022: 40, 2023: 50, 2024: 60},
                          RESTRICTED: {2022: 45, 2023: 55, 2024: 65}})
    assert {p.cash.provenance.tag for p in f.periods} == {CLEAN}
    assert "restricted cash" not in warnings_text(f)


# 2b. Derivations are per-year gap fillers: a year that reports the value uses it

def test_debt_current_2_of_3_years_components_fill_the_gap_only():
    f = normalize_inline({"DebtCurrent": {2023: 70, 2024: 80},
                          "LongTermDebtCurrent": {2022: 5, 2023: 6, 2024: 7},
                          "CommercialPaper": {2022: 1, 2023: 2, 2024: 3}})
    std = {p.fiscal_year: p.short_term_debt for p in f.periods}
    assert {y: (v.value, v.provenance.tag, v.provenance.origin) for y, v in std.items()} == {
        2024: (80, "DebtCurrent", ValueOrigin.REPORTED),
        2023: (70, "DebtCurrent", ValueOrigin.REPORTED),
        2022: (6, "LongTermDebtCurrent + CommercialPaper", ValueOrigin.DERIVED)}
    assert std[2024].provenance.note is None
    assert "DebtCurrent not reported" in std[2022].provenance.note
    assert "Not reported (so not included): ShortTermBorrowings." in std[2022].provenance.note
    text = warnings_text(f)
    assert ("Short-term debt (incl. current portion of LTD): the SEC tag used differs between "
            "periods (FY2024: DebtCurrent; FY2023: DebtCurrent; FY2022: LongTermDebtCurrent + "
            "CommercialPaper)") in text
    # Only the derived year is listed in the combined component warning.
    assert ("Short-term debt is the sum of the reported components only (FY2022: "
            "LongTermDebtCurrent and CommercialPaper only, ShortTermBorrowings not reported).") \
        in text


def test_reported_value_always_wins_over_derivation_covering_all_years():
    f = normalize_inline({
        # Reported tags exist for FY2024 only; derivations could cover all three years.
        "DebtCurrent": {2024: 999},
        "LongTermDebtCurrent": {2022: 5, 2023: 6, 2024: 7},
        "LongTermDebtNoncurrent": {2024: 888},
        "LongTermDebt": {2022: 50, 2023: 60, 2024: 70},
        "Liabilities": {2024: 777},
        "LiabilitiesAndStockholdersEquity": {2022: 100, 2023: 110, 2024: 120},
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest":
            {2022: 30, 2023: 35, 2024: 40},
    })
    p24, p23, p22 = f.period(2024), f.period(2023), f.period(2022)
    assert (p24.get("short_term_debt"), p24.get("long_term_debt"),
            p24.get("total_liabilities")) == (999, 888, 777)
    assert (p23.get("short_term_debt"), p23.get("long_term_debt"),
            p23.get("total_liabilities")) == (6, 54, 75)
    assert (p22.get("short_term_debt"), p22.get("long_term_debt"),
            p22.get("total_liabilities")) == (5, 45, 70)
    text = warnings_text(f)
    for field, tag in (("short_term_debt", "DebtCurrent"),
                       ("long_term_debt", "LongTermDebtNoncurrent"),
                       ("total_liabilities", "Liabilities")):
        v24, v23 = getattr(p24, field), getattr(p23, field)
        assert v24.provenance.origin == ValueOrigin.REPORTED
        assert v24.provenance.tag == tag
        assert v23.provenance.origin == ValueOrigin.DERIVED
        assert f"{tag} not reported" in v23.provenance.note
        assert f"FY2024: {tag}; FY2023: " in text  # tag-switch warning flags mixed methods
    assert "is reported for this period" not in text
    assert all("is reported for this period" not in (getattr(p, fld).provenance.note or "")
               for p in f.periods
               for fld in ("short_term_debt", "long_term_debt", "total_liabilities"))


# 3. Currency change across fiscal years

def test_currency_change_between_periods_warns_once_no_conversion():
    f = normalize_inline({}, currency_by_year={2022: "EUR"})
    assert [p.currency for p in f.periods] == ["USD", "USD", "EUR"]
    assert f.period(2022).get("net_income") == 10  # EUR value, not converted
    assert f.period(2024).get("net_income") == 12
    expected = ("Reporting currency changes between periods (FY2022: EUR; FY2023-FY2024: USD). "
                "Figures are never converted, so comparisons across the change are not "
                "meaningful.")
    assert f.warnings.count(expected) == 1


def test_no_currency_change_warning_when_single_currency(msft):
    assert "Reporting currency changes" not in warnings_text(msft)
    assert "Reporting currency changes" not in warnings_text(synthetic("non_usd"))
