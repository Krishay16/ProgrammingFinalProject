"""Tests for src/pdf_extractor.py (Person 3). All PDFs are SYNTHETIC, built in memory."""
import os

import pytest

from src.manual_input import table_to_financials
from src.models import ALL_FIELDS, SourceType, Units
from src.pdf_extractor import (MAX_FILE_BYTES, SCANNED_MESSAGE, UNITS_WARNING,
                               detect_currency, detect_number_style, detect_units,
                               detect_years, extract_financials, match_label,
                               parse_number, result_to_table)
from tests.fixtures.sample_data import make_sample_financials
from tests.pdf_builders import (SAMPLE_PDF_PATH, make_blank_pdf, make_pdf,
                                make_sample_statement_pdf)


def _value(result, field, year):
    matches = [it for it in result.items if it.field == field and it.fiscal_year == year]
    assert len(matches) == 1, (field, year, matches)
    return matches[0]


# ---------------------------------------------------------------- parse_number
@pytest.mark.parametrize("text, expected", [
    ("1,234", 1234.0), ("1 234", 1234.0), ("1.234,56", 1234.56), ("(1,234)", -1234.0),
    ("-1,234", -1234.0), ("1,234-", -1234.0), ("−1,234", -1234.0), ("0", 0.0),
    ("12 345,5", 12345.5),
])
def test_parse_number(text, expected):
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["—", "-", "n/a", "", "abc", None])
def test_parse_number_missing_or_text(text):
    assert parse_number(text) is None


def test_parse_number_with_document_style():
    assert parse_number("4.000", decimal_comma=True) == 4000.0     # European thousands
    assert parse_number("4.000") == 4.0                             # unknown: decimal point
    assert parse_number("1,5", decimal_comma=True) == 1.5
    assert parse_number("(1.234,5)", decimal_comma=True) == -1234.5
    assert parse_number("1,500", decimal_comma=False) == 1500.0


def test_detect_number_style():
    assert detect_number_style("Total 4.500,5  4.000") is True
    assert detect_number_style("Revenue 1,250.0 1,100.5") is False
    assert detect_number_style("Revenue 1 250 1 100") is None


# ---------------------------------------------------------------- detection
@pytest.mark.parametrize("text, units", [
    ("(in thousands)", Units.THOUSANDS), ("In millions of USD", Units.MILLIONS),
    ("(in $ millions)", Units.MILLIONS), ("En milliers d'euros", Units.THOUSANDS),
    ("en millions d'euros", Units.MILLIONS), ("Montants en k€", Units.THOUSANDS),
    ("MEUR", Units.MILLIONS), ("$m", Units.MILLIONS), ("in billions", Units.BILLIONS),
    ("Balance sheet", None),
    ("in thousands ... in millions", None),          # contradictory -> not guessed
])
def test_detect_units(text, units):
    assert detect_units(text) == units


@pytest.mark.parametrize("text, ccy", [
    ("in millions of USD", "USD"), ("US$ 1,000", "USD"), ("Montants en €", "EUR"),
    ("en milliers d'euros", "EUR"), ("£ thousands", "GBP"), ("GBP", "GBP"),
    ("en milliers de dirhams", "MAD"), ("MAD 000", "MAD"), ("Balance sheet", None),
    ("USD and EUR", None),                            # several -> None
])
def test_detect_currency(text, ccy):
    assert detect_currency(text) == ccy


def test_detect_years():
    assert detect_years("Income statement\n  2024   2023\nRevenue 10 9") == [2024, 2023]
    assert detect_years("Bilan\n2024\nTotal actif 10") == [2024]
    assert detect_years("Revenue 1999 1998") == []          # outside 2000-2035
    assert detect_years("No years here") == []


@pytest.mark.parametrize("label, field", [
    ("Total assets", "total_assets"), ("TOTAL ACTIF", "total_assets"),
    ("Total de l’actif", "total_assets"), ("Capitaux propres", "total_equity"),
    ("Résultat d'exploitation", "ebit"), ("Chiffre d'affaires", "revenue"),
    ("Cost of revenue", "cost_of_revenue"),            # longest match beats "revenue"
    ("Total current assets", "current_assets"),
    ("Net cash provided by operating activities", "operating_cash_flow"),
])
def test_match_label(label, field):
    assert match_label(label)[0] == field


def test_match_label_rejects_per_share_and_unknown_lines():
    assert match_label("Net income per share") is None
    assert match_label("Goodwill") is None


# ---------------------------------------------------------------- full extraction
def test_sample_statement_extracts_every_field_matching_synthetic_fixture():
    result = extract_financials([("sample.pdf", make_sample_statement_pdf())])
    assert result.units == Units.MILLIONS and result.currency == "USD"
    assert result.fiscal_years == [2024, 2023]
    assert result.warnings == [] and result.failed_files == []
    expected = make_sample_financials()
    for year in (2024, 2023):
        for field in ALL_FIELDS:
            item = _value(result, field, year)
            assert item.status == "ok", (field, year, item.note)
            assert item.value == pytest.approx(expected.period(year).get(field)), field


def test_signs_capex_and_interest_positive_cash_flows_keep_sign():
    result = extract_financials([("sample.pdf", make_sample_statement_pdf())])
    assert _value(result, "capex", 2024).value == 600_000_000.0           # was (600)
    assert _value(result, "interest_expense", 2024).value == 150_000_000.0
    assert "positive" in _value(result, "capex", 2024).note
    assert _value(result, "investing_cash_flow", 2024).value == -750_000_000.0


def test_evidence_kept_for_each_value():
    result = extract_financials([("sample.pdf", make_sample_statement_pdf())])
    item = _value(result, "total_assets", 2024)
    assert item.source_file == "sample.pdf" and item.page == 2
    assert item.original_text == "12,000" and item.matched_label == "Total assets"


def test_french_balance_sheet_in_thousands_of_euros():
    pdf = make_pdf([["Société Exemple SAS (SYNTHETIQUE)", "Bilan",
                     "En milliers d'euros", ("", "2024", "2023"),
                     ("Total actif", "12 345", "11 000"),
                     ("Capitaux propres", "4.500,5", "4.000"),
                     ("Résultat d'exploitation", "1 200", "(300)")]])
    result = extract_financials([("bilan.pdf", pdf)])
    assert result.units == Units.THOUSANDS and result.currency == "EUR"
    assert _value(result, "total_assets", 2024).value == 12_345_000.0
    assert _value(result, "total_equity", 2024).value == pytest.approx(4_500_500.0)
    assert _value(result, "total_equity", 2023).value == 4_000_000.0      # "4.000" = 4,000
    assert _value(result, "ebit", 2023).value == -300_000.0


def test_parentheses_negatives_for_a_loss():
    pdf = make_pdf([["Loss Co (SYNTHETIC)", "(in thousands of USD)", ("", "2024", "2023"),
                     ("Net income", "(1,234)", "56"), ("Operating income", "(900)", "(10)")]])
    result = extract_financials([("loss.pdf", pdf)])
    assert _value(result, "net_income", 2024).value == -1_234_000.0
    assert _value(result, "ebit", 2023).value == -10_000.0


def test_scanned_pdf_is_reported_not_guessed():
    result = extract_financials([("scan.pdf", make_blank_pdf())])
    assert result.scanned_files == ["scan.pdf"] and result.items == []
    assert any(SCANNED_MESSAGE in w for w in result.warnings)


def test_corrupted_and_invalid_files_fail_with_reasons():
    result = extract_financials([
        ("random.pdf", os.urandom(2000)),
        ("broken.pdf", b"%PDF-1.7 this is not really a pdf"),
        ("notes.txt", b"%PDF-1.4"),
        ("huge.pdf", b"%PDF" + b"0" * MAX_FILE_BYTES),
    ])
    reasons = " | ".join(result.failed_files)
    assert len(result.failed_files) == 4, reasons
    assert "random.pdf: not a valid PDF" in reasons
    assert "broken.pdf: the file is corrupted" in reasons
    assert "notes.txt: not a .pdf file" in reasons
    assert "huge.pdf: larger than 20 MB" in reasons
    assert result.items == []


def test_one_bad_file_does_not_stop_the_good_one():
    result = extract_financials([("bad.pdf", b"garbage"),
                                 ("sample.pdf", make_sample_statement_pdf())])
    assert len(result.failed_files) == 1 and len(result.items) == 40


def test_unknown_units_keep_raw_numbers_and_warn():
    pdf = make_pdf([["Company Without Units Ltd (SYNTHETIC)", "Statement of profit or loss",
                     ("", "2024", "2023"), ("Revenue", "1,500", "1,400")]])
    result = extract_financials([("nounits.pdf", pdf)])
    assert result.units is None and UNITS_WARNING in result.warnings
    assert _value(result, "revenue", 2024).value == 1500.0


def test_wrong_number_of_values_is_ambiguous():
    pdf = make_pdf([["Co (SYNTHETIC)", "(in millions of USD)", ("", "2024", "2023"),
                     ("Revenue", "5", "1,500", "1,400")]])          # "5" = note number
    item = _value(extract_financials([("x.pdf", pdf)]), "revenue", 2024)
    assert item.status == "ambiguous" and item.value == 1_500_000_000.0
    assert "3 numbers for 2 year columns" in item.note


def test_conflicting_values_are_all_kept_as_ambiguous_and_left_blank_in_table():
    page = ["Co (SYNTHETIC)", "(in millions of USD)", ("", "2024", "2023")]
    pdf = make_pdf([page + [("Revenue", "1,500", "1,400")],
                    page + [("Revenue", "1,550", "1,400")]])
    result = extract_financials([("x.pdf", pdf)])
    rev24 = [it for it in result.items if it.field == "revenue" and it.fiscal_year == 2024]
    assert len(rev24) == 2 and all(it.status == "ambiguous" for it in rev24)
    assert "p.1" in rev24[0].note and "p.2" in rev24[0].note
    rev23 = [it for it in result.items if it.field == "revenue" and it.fiscal_year == 2023]
    assert len(rev23) == 1 and rev23[0].status == "ok"              # same value: merged
    df, flags = result_to_table(result)
    assert df.at["revenue", "2024"] is None and ("revenue", "2024") in flags
    assert df.at["revenue", "2023"] == "1400"


def test_unclear_number_style_is_flagged():
    pdf = make_pdf([["Co (SYNTHETIC)", "(in thousands of EUR)", ("", "2024", "2023"),
                     ("Total assets", "4.000", "3 900")]])
    item = _value(extract_financials([("x.pdf", pdf)]), "total_assets", 2024)
    assert item.status == "ambiguous" and "could mean" in item.note


# ---------------------------------------------------------------- table for confirmation
def test_result_to_table_uses_original_units_and_round_trips():
    result = extract_financials([("sample.pdf", make_sample_statement_pdf())])
    df, flags = result_to_table(result)
    assert flags == {}
    assert df.at["revenue", "2024"] == "9000" and df.at["capex", "2023"] == "550"
    f = table_to_financials(df, "Sample Manufacturing Co (SYNTHETIC)", "USD",
                            result.units, SourceType.PDF, "sample.pdf")
    expected = make_sample_financials()
    for field in ALL_FIELDS:
        assert f.period(2024).get(field) == pytest.approx(expected.period(2024).get(field))


def test_saved_fixture_pdf_matches_builder():
    """tests/fixtures/sample_statement_SYNTHETIC.pdf is used by the demo and test C."""
    assert SAMPLE_PDF_PATH.exists()
    result = extract_financials([(SAMPLE_PDF_PATH.name, SAMPLE_PDF_PATH.read_bytes())])
    assert len(result.items) == 40 and result.units == Units.MILLIONS
