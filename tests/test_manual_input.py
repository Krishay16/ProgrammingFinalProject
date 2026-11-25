"""Tests for src/manual_input.py (Person 3). All offline, no Streamlit needed."""
import math

import pandas as pd
import pytest

from src.manual_input import (blocked_ratios, empty_table, financials_from_json,
                              financials_to_json, financials_to_table, parse_cell,
                              resize_table, table_to_financials, unreadable_cells)
from src.models import (ALL_FIELDS, SourceType, Units, ValueOrigin, VerificationStatus)
from tests.fixtures.sample_data import make_sample_financials


def _table(values: dict[tuple[str, str], object], years=(2024, 2023)) -> pd.DataFrame:
    df = empty_table(list(years))
    for (field, year), v in values.items():
        df.at[field, year] = v
    return df


def _convert(df, units=Units.UNITS, currency="EUR", source=SourceType.MANUAL):
    return table_to_financials(df, "Test Co", currency, units, source, "Manual entry")


# ---------------------------------------------------------------- empty_table
def test_empty_table_shape_order_and_all_missing():
    df = empty_table([2022, 2024, 2023])
    assert list(df.index) == ALL_FIELDS                       # statement order
    assert [c for c in df.columns if c != "Line item"] == ["2024", "2023", "2022"]
    assert df.at["total_assets", "Line item"] == "Total assets"
    assert df[["2024", "2023", "2022"]].isna().all().all()    # missing, never 0


def test_resize_table_keeps_values_for_remaining_years():
    df = _table({("revenue", "2024"): "100", ("revenue", "2023"): "90"})
    bigger = resize_table(df, [2024, 2023, 2022])
    assert bigger.at["revenue", "2024"] == "100" and bigger.at["revenue", "2023"] == "90"
    assert pd.isna(bigger.at["revenue", "2022"])
    smaller = resize_table(df, [2024])
    assert "2023" not in smaller.columns and smaller.at["revenue", "2024"] == "100"


# ---------------------------------------------------------------- parse_cell
@pytest.mark.parametrize("text, expected", [
    ("1234", 1234.0),
    ("1,234.5", 1234.5),          # US format
    ("1,234,567", 1234567.0),
    ("1.234,5", 1234.5),          # European format
    ("1.234.567", 1234567.0),
    ("1234,5", 1234.5),           # decimal comma
    ("1 234 567", 1234567.0),     # space thousands separator
    ("1'234", 1234.0),            # Swiss apostrophe
    ("(1,234)", -1234.0),         # accounting negative
    ("-1,234", -1234.0),
    ("$1,234", 1234.0),
    ("0", 0.0),                   # a typed zero is a real zero
    ("1.234", 1.234),             # documented rule: a single dot is a decimal point
    (1500, 1500.0),
    (2.5, 2.5),
])
def test_parse_cell_numbers(text, expected):
    assert parse_cell(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [None, float("nan"), "", "   ", "-", "—", "n/a", "N/A"])
def test_parse_cell_missing_is_none(text):
    assert parse_cell(text) is None


@pytest.mark.parametrize("text", ["12abc", "about 5", "1,23,4", "()", "True", True])
def test_parse_cell_unreadable_is_none_not_guessed(text):
    assert parse_cell(text) is None


# ---------------------------------------------------------------- table_to_financials
@pytest.mark.parametrize("units, expected", [
    (Units.THOUSANDS, 1_234_000.0),     # 1,234 thousand
    (Units.MILLIONS, 1_234_000_000.0),  # 1,234 million
    (Units.BILLIONS, 1_234_000_000_000.0),
    (Units.UNITS, 1_234.0),
])
def test_units_multiplication(units, expected):
    f = _convert(_table({("revenue", "2024"): "1,234"}), units=units)
    assert f.latest().get("revenue") == pytest.approx(expected)
    assert f.latest().original_units == units


def test_blank_is_missing_and_zero_is_zero():
    f = _convert(_table({("short_term_debt", "2024"): "0", ("revenue", "2024"): "500"}))
    p = f.latest()
    assert p.get("short_term_debt") == 0.0
    assert p.get("long_term_debt") is None            # left blank -> missing
    assert "long_term_debt" in p.missing_fields()
    assert "short_term_debt" not in p.missing_fields()


def test_parentheses_and_european_format_in_table():
    f = _convert(_table({("net_income", "2024"): "(1.234,5)",
                         ("revenue", "2024"): "10.000,0"}), units=Units.THOUSANDS)
    assert f.latest().get("net_income") == pytest.approx(-1_234_500.0)   # -1234.5 * 1000
    assert f.latest().get("revenue") == pytest.approx(10_000_000.0)


def test_empty_year_is_skipped_and_periods_newest_first():
    df = _table({("revenue", "2022"): "80", ("revenue", "2024"): "100"},
                years=(2024, 2023, 2022))
    f = _convert(df)
    assert [p.fiscal_year for p in f.periods] == [2024, 2022]   # 2023 empty -> skipped


def test_provenance_manual_user_confirmed_and_currency_kept():
    f = _convert(_table({("cash", "2024"): "(50)"}), currency="MAD")
    p = f.latest()
    prov = p.cash.provenance
    assert prov.source_type == SourceType.MANUAL
    assert prov.origin == ValueOrigin.MANUAL
    assert prov.verification == VerificationStatus.USER_CONFIRMED
    assert prov.original_text == "(50)"
    assert p.currency == "MAD" and f.source_type == SourceType.MANUAL
    assert p.is_annual is True


def test_pdf_source_gets_reported_origin():
    f = _convert(_table({("cash", "2024"): "50"}), source=SourceType.PDF)
    assert f.latest().cash.provenance.origin == ValueOrigin.REPORTED
    assert f.latest().cash.provenance.verification == VerificationStatus.USER_CONFIRMED


def test_unreadable_cell_is_missing_with_warning():
    df = _table({("revenue", "2024"): "12abc", ("cash", "2024"): "10"})
    assert unreadable_cells(df) == [("revenue", "2024", "12abc")]
    f = _convert(df)
    assert f.latest().get("revenue") is None
    assert any("12abc" in w for w in f.warnings)


def test_completely_empty_table_gives_no_periods():
    assert _convert(empty_table([2024])).periods == []


# ---------------------------------------------------------------- JSON and reload
def test_json_round_trip():
    f = _convert(_table({("revenue", "2024"): "1,234.5", ("revenue", "2023"): "(10)",
                         ("capex", "2024"): "0"}), units=Units.MILLIONS)
    back = financials_from_json(financials_to_json(f))
    assert back == f


def test_json_round_trip_of_synthetic_fixture():
    f = make_sample_financials()
    assert financials_from_json(financials_to_json(f)) == f


def test_financials_to_table_restores_original_units():
    df = _table({("revenue", "2024"): "1,234.5", ("total_assets", "2023"): "900"})
    f = _convert(df, units=Units.MILLIONS, currency="GBP")
    table, currency, units = financials_to_table(f)
    assert currency == "GBP" and units == Units.MILLIONS
    assert table.at["revenue", "2024"] == "1234.5"
    assert table.at["total_assets", "2023"] == "900"
    assert pd.isna(table.at["cash", "2024"])
    # and converting again gives the same values
    again = _convert(table, units=units, currency=currency)
    assert again.latest().get("revenue") == f.latest().get("revenue")


# ---------------------------------------------------------------- blocked ratios
def test_blocked_ratios_for_balance_sheet_and_income_statement_only():
    df = _table({("current_assets", "2024"): "200", ("current_liabilities", "2024"): "100",
                 ("revenue", "2024"): "500", ("ebit", "2024"): "50"}, years=(2024,))
    blocked = blocked_ratios(_convert(df))[2024]
    assert "Current Ratio" not in blocked and "Operating Margin" not in blocked
    assert blocked["Interest Coverage"] == ["Interest expense"]
    assert "Operating cash flow" in blocked["Free Cash Flow"]
    assert blocked["Revenue Growth"] == ["Revenue for FY2023"]


def test_blocked_ratios_ebitda_derived_from_ebit_and_da():
    df = _table({k: "10" for k in [("short_term_debt", "2024"), ("long_term_debt", "2024"),
                                   ("cash", "2024"), ("ebit", "2024"),
                                   ("depreciation_amortization", "2024")]}, years=(2024,))
    assert "Net Debt / EBITDA" not in blocked_ratios(_convert(df))[2024]


def test_blocked_ratios_none_for_complete_synthetic_sample():
    blocked = blocked_ratios(make_sample_financials())
    assert blocked[2024] == {} and blocked[2023] == {}
    assert list(blocked[2022]) == ["Revenue Growth"]   # no FY2021 in the fixture
    assert not math.isnan(make_sample_financials().latest().get("revenue"))
