"""Offline tests for scripts/reconcile.py (Person 2). All data here is SYNTHETIC.

No network: the fetch tests use a fake client and SYNTHETIC SEC-shaped dicts; the compare
tests use SYNTHETIC CSVs written to tmp_path.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import reconcile as rc
from src.models import Units
from src.pdf_extractor import parse_number

FIXED_NOW = lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)  # noqa: E731

# --------------------------------------------------------------------------- SYNTHETIC SEC data

SYN_CIK = "0000000042"
SYN_ACCN = "0000000042-25-000007"          # SYNTHETIC accession
SYN_ACCN_OLD = "0000000042-24-000003"      # SYNTHETIC accession


def _flow(val, start, end, accn=SYN_ACCN, filed="2025-08-01"):
    return {"val": val, "start": start, "end": end, "form": "10-K", "fp": "FY",
            "filed": filed, "accn": accn, "fy": 2025}


def _inst(val, end, accn=SYN_ACCN, filed="2025-08-01"):
    return {"val": val, "end": end, "form": "10-K", "fp": "FY", "filed": filed,
            "accn": accn, "fy": 2025}


def _tag(*rows):
    return {"units": {"USD": list(rows)}}


def synthetic_facts() -> dict:
    """SYNTHETIC companyfacts: FY2025 and FY2024 (year ending 30 June)."""
    y25, y24 = ("2024-07-01", "2025-06-30"), ("2023-07-01", "2024-06-30")
    return {"cik": 42, "entityName": "SYNTHETIC Corp", "facts": {"us-gaap": {
        "NetIncomeLoss": _tag(_flow(1_500_000_000, *y25), _flow(1_200_000_000, *y24)),
        "Revenues": _tag(_flow(10_000_000_000, *y25), _flow(9_000_000_000, *y24)),
        "OperatingIncomeLoss": _tag(_flow(2_000_000_000, *y25), _flow(1_800_000_000, *y24)),
        "Assets": _tag(_inst(50_000_000_000, "2025-06-30"), _inst(45_000_000_000, "2024-06-30")),
        "PaymentsToAcquirePropertyPlantAndEquipment":
            _tag(_flow(700_000_000, *y25), _flow(650_000_000, *y24)),
    }}}


def synthetic_submissions() -> dict:
    return {"cik": "42", "name": "SYNTHETIC Corp", "sic": "3571", "tickers": ["SYNT"],
            "filings": {"recent": {
                "accessionNumber": [SYN_ACCN, SYN_ACCN_OLD],
                "primaryDocument": ["synt-20250630.htm", "synt-20240630.htm"],
                "form": ["10-K", "10-K"],
                "filingDate": ["2025-08-01", "2024-08-01"],
                "reportDate": ["2025-06-30", "2024-06-30"]}}}


class FakeClient:
    """Stands in for SecClient; counts calls so we can prove compare never fetches."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_company_tickers(self):
        self.calls.append("tickers")
        return {"0": {"cik_str": 42, "ticker": "SYNT", "title": "SYNTHETIC Corp"}}

    def get_submissions(self, cik):
        self.calls.append(f"submissions:{cik}")
        return synthetic_submissions()

    def get_company_facts(self, cik):
        self.calls.append(f"facts:{cik}")
        return synthetic_facts()


# --------------------------------------------------------------------------- CSV helpers

def _write(path: Path, columns: list[str], rows: list[dict]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})
    return path


def app_row(field="revenue", value="245122000000", year="2025", **kw) -> dict:
    row = {"fetched_at": "2026-01-01T00:00:00+00:00", "ticker": "SYNT", "cik": SYN_CIK,
           "company_name": "SYNTHETIC Corp", "fiscal_year": year, "currency": "USD",
           "field": field, "app_value": value, "origin": "reported", "tag": "Revenues",
           "form": "10-K", "accession": SYN_ACCN, "filing_date": "2025-08-01",
           "source_url": "https://example.invalid/SYNTHETIC", "filing_url": "", "note": ""}
    row.update(kw)
    return row


def exp_row(field="revenue", printed="", units="MILLIONS", year="2025", **kw) -> dict:
    row = {"ticker": "SYNT", "fiscal_year": year, "field": field,
           "where_in_filing": "Income statement — Revenue [confirm exact line label]",
           "filing_value_as_printed": printed, "filing_units": units,
           "filing_url": "https://example.invalid/SYNTHETIC.htm", "explanation": ""}
    row.update(kw)
    return row


# --------------------------------------------------------------------------- parse_number (P3)

@pytest.mark.parametrize("text, expected", [
    ("(44,477)", -44477.0),
    ("1,234", 1234.0),
    ("5", 5.0),
])
def test_parse_number_handles_filing_formats(text, expected):
    assert parse_number(text, decimal_comma=False) == expected


def test_parse_number_after_dollar_strip():
    assert parse_number("$ 5".replace("$", "").strip(), decimal_comma=False) == 5.0


def test_parse_number_dash_is_none():
    assert parse_number("—", decimal_comma=False) is None


# --------------------------------------------------------------------------- parsing

@pytest.mark.parametrize("text, expected", [
    ("(44,477)", Decimal("-44477")),
    ("1,234", Decimal("1234")),
    ("$ 5", Decimal("5")),
    ("$(1,234)", Decimal("-1234")),
    ("0", Decimal("0")),
    ("1,234.5", Decimal("1234.5")),
])
def test_parse_filing_value(text, expected):
    assert rc.parse_filing_value(text) == expected


@pytest.mark.parametrize("text", ["", "   ", None])
def test_parse_filing_value_empty_is_none(text):
    assert rc.parse_filing_value(text) is None


@pytest.mark.parametrize("text", ["—", "abc", "12abc"])
def test_parse_filing_value_unreadable_raises(text):
    with pytest.raises(ValueError):
        rc.parse_filing_value(text)


@pytest.mark.parametrize("text, expected", [
    ("MILLIONS", Units.MILLIONS), ("millions", Units.MILLIONS), (" Thousands ", Units.THOUSANDS),
    ("billions", Units.BILLIONS), ("UNITS", Units.UNITS), ("ones", Units.UNITS),
])
def test_parse_units(text, expected):
    assert rc.parse_units(text) is expected


@pytest.mark.parametrize("text", ["", None, "mn", "in millions", "hundreds"])
def test_parse_units_unknown_raises(text):
    with pytest.raises(ValueError):
        rc.parse_units(text)


def test_format_app_value_exact():
    assert rc.format_app_value(None) == ""
    assert rc.format_app_value(245_122_000_000.0) == "245122000000"
    assert rc.format_app_value(-5.5) == "-5.5"


# --------------------------------------------------------------------------- statuses

def test_match_exact_after_units():
    c = rc.compare_row(exp_row(printed="245,122"), app_row(value="245122000000"))
    assert c.status is rc.Status.MATCH and c.difference == 0


def test_tolerance_boundary_exactly_half_unit_matches():
    c = rc.compare_row(exp_row(printed="245,122"), app_row(value="245122500000"))
    assert c.status is rc.Status.MATCH
    c = rc.compare_row(exp_row(printed="245,122"), app_row(value="245121500000"))
    assert c.status is rc.Status.MATCH


def test_tolerance_boundary_just_above_half_unit_fails():
    c = rc.compare_row(exp_row(printed="245,122"), app_row(value="245122500001"))
    assert c.status is rc.Status.MISMATCH
    assert c.difference == Decimal("500001")


def test_tolerance_thousands():
    ok = rc.compare_row(exp_row(printed="1,000", units="THOUSANDS"), app_row(value="1000500"))
    bad = rc.compare_row(exp_row(printed="1,000", units="THOUSANDS"), app_row(value="1000501"))
    assert ok.status is rc.Status.MATCH and bad.status is rc.Status.MISMATCH


def test_signed_comparison_for_normal_fields():
    c = rc.compare_row(exp_row(field="net_income", printed="(5)"), app_row(field="net_income",
                                                                           value="5000000"))
    assert c.status is rc.Status.MISMATCH


@pytest.mark.parametrize("field", ["capex", "interest_expense"])
def test_abs_comparison_for_positive_fields(field):
    c = rc.compare_row(exp_row(field=field, printed="(44,477)"),
                       app_row(field=field, value="44477000000"))
    assert c.status is rc.Status.MATCH


def test_not_checked_when_filing_value_empty():
    c = rc.compare_row(exp_row(printed=""), app_row())
    assert c.status is rc.Status.NOT_CHECKED and c.difference is None


def test_app_value_missing_never_zero():
    c = rc.compare_row(exp_row(printed="0", units="MILLIONS"), app_row(value=""))
    assert c.status is rc.Status.APP_VALUE_MISSING and c.difference is None


def test_no_app_row():
    c = rc.compare_row(exp_row(printed="1"), None)
    assert c.status is rc.Status.NO_APP_ROW and c.difference is None


def test_input_error_for_dash():
    c = rc.compare_row(exp_row(printed="—"), app_row())
    assert c.status is rc.Status.INPUT_ERROR and c.difference is None
    assert "type 0" in c.error


def test_input_error_for_unknown_units():
    c = rc.compare_row(exp_row(printed="1", units="lakh"), app_row())
    assert c.status is rc.Status.INPUT_ERROR


def test_input_error_for_missing_units():
    c = rc.compare_row(exp_row(printed="1", units=""), app_row())
    assert c.status is rc.Status.INPUT_ERROR


def test_compare_duplicate_and_bad_year_are_input_errors():
    comps = rc.compare([exp_row(printed="1"), exp_row(printed="1"), exp_row(year="FY25")],
                       [app_row()])
    assert [c.status for c in comps] == [rc.Status.MISMATCH, rc.Status.INPUT_ERROR,
                                         rc.Status.INPUT_ERROR]


def test_compare_key_is_case_insensitive_ticker_and_int_year():
    comps = rc.compare([exp_row(printed="245,122", ticker="synt", year=" 2025 ")], [app_row()])
    assert comps[0].status is rc.Status.MATCH


def test_pinned_year_does_not_follow_newer_periods():
    comps = rc.compare([exp_row(printed="245,122", year="2025")],
                       [app_row(year="2026", value="999000000"), app_row(year="2025")])
    assert comps[0].status is rc.Status.MATCH
    assert comps[0].app["fiscal_year"] == "2025"


# --------------------------------------------------------------------------- run_compare / markdown

def _compare_files(tmp_path, expected, app):
    a = _write(tmp_path / "app.csv", rc.APP_COLUMNS, app)
    e = _write(tmp_path / "exp.csv", rc.EXPECTED_COLUMNS, expected)
    md = tmp_path / "out.md"
    comps = rc.run_compare(a, e, md, now=FIXED_NOW, out=lambda s: None)
    return comps, md.read_text(encoding="utf-8")


def test_markdown_contains_all_statuses_and_header(tmp_path):
    expected = [exp_row(printed="245,122"),                                     # MATCH
                exp_row(field="ebit", printed="1"),                             # MISMATCH
                exp_row(field="net_income"),                                    # NOT CHECKED
                exp_row(field="total_assets", printed="5"),                     # APP MISSING
                exp_row(field="capex", printed="5"),                            # NO APP ROW
                exp_row(field="cash", printed="—")]                             # INPUT ERROR
    app = [app_row(), app_row(field="ebit", value="2000000", tag="OperatingIncomeLoss"),
           app_row(field="net_income"), app_row(field="total_assets", value=""),
           app_row(field="cash")]
    comps, md = _compare_files(tmp_path, expected, app)
    assert [c.status for c in comps] == [rc.Status.MATCH, rc.Status.MISMATCH,
                                         rc.Status.NOT_CHECKED, rc.Status.APP_VALUE_MISSING,
                                         rc.Status.NO_APP_ROW, rc.Status.INPUT_ERROR]
    for s in rc.Status:
        assert s.value in md
    assert "typed by hand by Person 2 from the official 10-K" in md
    assert "2026-01-01T00:00:00+00:00" in md          # fetch date
    assert "2026-01-02T03:04:05+00:00" in md          # comparison date
    assert "+1 millions" in md                        # difference in filing units
    assert "OperatingIncomeLoss" in md                # provenance next to the mismatch
    assert md.count("EXPLANATION NEEDED") == 4        # MISMATCH, APP MISSING, NO ROW, INPUT ERR


def test_markdown_preserves_explanation(tmp_path):
    expected = [exp_row(field="ebit", printed="1",
                        explanation="SYNTHETIC: tag choice differs | see note")]
    _comps, md = _compare_files(tmp_path, expected, [app_row(field="ebit", value="2000000")])
    assert "SYNTHETIC: tag choice differs \\| see note" in md
    assert "EXPLANATION NEEDED" not in md


def test_rerunning_compare_is_reproducible(tmp_path):
    expected = [exp_row(printed="245,122")]
    _c, md1 = _compare_files(tmp_path, expected, [app_row()])
    _c, md2 = _compare_files(tmp_path, expected, [app_row()])
    assert md1 == md2


def test_compare_missing_file_raises(tmp_path):
    with pytest.raises(rc.ReconcileError):
        rc.run_compare(tmp_path / "nope.csv", tmp_path / "nope2.csv", tmp_path / "x.md",
                       out=lambda s: None)


def test_compare_mode_makes_no_network_call(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network/SecClient used in --compare")
    monkeypatch.setattr(rc, "SecClient", boom)
    a = _write(tmp_path / "a.csv", rc.APP_COLUMNS, [app_row()])
    e = _write(tmp_path / "e.csv", rc.EXPECTED_COLUMNS, [exp_row(printed="245,122")])
    assert rc.main(["--compare", "--app-csv", str(a), "--expected-csv", str(e),
                    "--md", str(tmp_path / "r.md")]) == 0


# --------------------------------------------------------------------------- SEC helpers

def test_accession_and_form_from_location():
    assert rc.accession_from_location(f"10-K accn {SYN_ACCN}") == SYN_ACCN
    assert rc.form_from_location(f"10-K/A accn {SYN_ACCN}") == "10-K/A"
    assert rc.accession_from_location(None) is None


def test_build_filing_url():
    assert rc.build_filing_url(SYN_CIK, SYN_ACCN, "synt-20250630.htm") == (
        "https://www.sec.gov/Archives/edgar/data/42/000000004225000007/synt-20250630.htm")


def test_filing_url_empty_when_accession_unknown():
    idx = rc.filing_index(synthetic_submissions())
    assert rc.filing_url_for(SYN_CIK, "0000000042-99-999999", idx) == ""


def test_lookup_ticker_exact_only():
    tickers = {"0": {"cik_str": 42, "ticker": "SYNT", "title": "SYNTHETIC Corp"},
               "1": {"cik_str": 43, "ticker": "SYNTX", "title": "SYNTHETIC X"}}
    assert rc.lookup_ticker(tickers, "synt") == (SYN_CIK, "SYNTHETIC Corp")
    with pytest.raises(rc.ReconcileError):
        rc.lookup_ticker(tickers, "SYN")


def test_lookup_ticker_ambiguous_refuses():
    tickers = {"0": {"cik_str": 42, "ticker": "SYNT", "title": "A"},
               "1": {"cik_str": 43, "ticker": "SYNT", "title": "B"}}
    with pytest.raises(rc.ReconcileError):
        rc.lookup_ticker(tickers, "SYNT")


# --------------------------------------------------------------------------- fetch (fake client)

def test_fetch_writes_app_csv_and_template(tmp_path):
    app_csv, exp_csv = tmp_path / "app.csv", tmp_path / "exp.csv"
    lines: list[str] = []
    rc.run_fetch(["SYNT"], FakeClient(), app_csv, exp_csv, now=FIXED_NOW, out=lines.append)

    app = rc.read_csv(app_csv)
    assert list(app[0].keys()) == rc.APP_COLUMNS
    assert len(app) == 2 * 20                                  # 2 periods x ALL_FIELDS
    rev = next(r for r in app if r["field"] == "revenue" and r["fiscal_year"] == "2025")
    assert rev["app_value"] == "10000000000" and rev["tag"] == "Revenues"
    assert rev["accession"] == SYN_ACCN and rev["form"] == "10-K"
    assert rev["filing_url"].endswith("/42/000000004225000007/synt-20250630.htm")
    assert rev["fetched_at"] == "2026-01-02T03:04:05+00:00"
    cash = next(r for r in app if r["field"] == "cash" and r["fiscal_year"] == "2025")
    assert cash["app_value"] == ""                             # missing -> empty, not 0

    exp = rc.read_csv(exp_csv)
    assert list(exp[0].keys()) == rc.EXPECTED_COLUMNS
    keys = [(r["fiscal_year"], r["field"]) for r in exp]
    assert keys == [("2025", f) for f in rc.LATEST_YEAR_FIELDS] + [("2024", "net_income")]
    assert all(r["filing_value_as_printed"] == "" and r["filing_units"] == ""
               and r["explanation"] == "" for r in exp)
    assert all(r["filing_url"].endswith("synt-20250630.htm") for r in exp)
    assert all(rc.CONFIRM in r["where_in_filing"] for r in exp)
    assert "comparative" in exp[-1]["where_in_filing"]
    out = "\n".join(lines)
    assert SYN_ACCN in out and "2025-08-01" in out


def test_fetch_never_overwrites_expected_csv(tmp_path):
    exp_csv = tmp_path / "exp.csv"
    exp_csv.write_bytes(b"ticker,fiscal_year,field\nSYNT,2025,revenue,MY TYPED VALUE\n")
    before = exp_csv.read_bytes()
    lines: list[str] = []
    rc.run_fetch(["SYNT"], FakeClient(), tmp_path / "app.csv", exp_csv, out=lines.append)
    assert exp_csv.read_bytes() == before
    assert any("left untouched" in l for l in lines)


def test_fetch_failure_writes_nothing(tmp_path):
    app_csv, exp_csv = tmp_path / "app.csv", tmp_path / "exp.csv"
    with pytest.raises(rc.ReconcileError):
        rc.run_fetch(["SYNT", "NOPE"], FakeClient(), app_csv, exp_csv, out=lambda s: None)
    assert not app_csv.exists() and not exp_csv.exists()


def test_fetch_then_compare_roundtrip(tmp_path):
    app_csv, exp_csv, md = tmp_path / "app.csv", tmp_path / "exp.csv", tmp_path / "r.md"
    rc.run_fetch(["SYNT"], FakeClient(), app_csv, exp_csv, out=lambda s: None)
    rows = rc.read_csv(exp_csv)
    rows[0].update(filing_value_as_printed="10,000", filing_units="millions")   # revenue
    _write(exp_csv, rc.EXPECTED_COLUMNS, rows)
    comps = rc.run_compare(app_csv, exp_csv, md, out=lambda s: None)
    assert comps[0].status is rc.Status.MATCH
    assert all(c.status is rc.Status.NOT_CHECKED for c in comps[1:]
               if c.key[2] not in ("current_assets", "current_liabilities", "total_equity",
                                   "operating_cash_flow"))
    # fields absent from the SYNTHETIC facts are APP VALUE MISSING, never compared as 0
    missing = [c for c in comps if c.key[2] == "current_assets"]
    assert missing[0].status is rc.Status.APP_VALUE_MISSING
