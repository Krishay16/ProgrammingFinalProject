"""Owned by Person 2: reconcile app values (SEC EDGAR -> normalizer) with the official 10-K.

Evidence that the app's key numbers match the official filings. NOT run by pytest (the offline
tests import the functions; tests/test_reconciliation_live.py does a live run).

Run from the repository root:

    .venv/bin/python scripts/reconcile.py                    # FETCH (network)
    .venv/bin/python scripts/reconcile.py --tickers MSFT AAPL
    .venv/bin/python scripts/reconcile.py --compare          # COMPARE (no network)

FETCH mode
    For each ticker: exact ticker -> CIK lookup in the SEC ticker list (no fuzzy search),
    submissions + companyfacts through SecClient, then normalize_company_facts (the same code
    the app uses). Writes docs/reconciliation_app_values.csv (every field of every period,
    empty cell = app value missing, never 0) and, ONLY IF IT DOES NOT EXIST YET,
    docs/reconciliation_expected.csv: a template whose filing values Person 2 types by hand
    from the official 10-K. An existing expected CSV is never modified. If any ticker fails,
    nothing is written.

COMPARE mode
    Reads only the two saved CSVs (reproducible, no network) and writes docs/reconciliation.md.

Typing the expected CSV (by hand, from the 10-K document at filing_url)
    filing_value_as_printed  the number exactly as printed, e.g. "(44,477)" or "245,122".
                             If the filing shows a dash "—" for zero, type 0 (a dash is
                             read as "no value" and gives INPUT ERROR).
    filing_units             UNITS / ONES, THOUSANDS, MILLIONS or BILLIONS (case-insensitive),
                             from the statement header ("In millions").
    explanation              only for a mismatch, written after investigating it.

Comparison rules
    * The printed value is parsed with src.pdf_extractor.parse_number(decimal_comma=False)
      after removing "$" and spaces, converted to Decimal(str(value)) and multiplied by the
      units. Empty -> NOT CHECKED. Unparseable or unknown units -> INPUT ERROR.
    * capex and interest_expense are stored as positive amounts in the app, so their absolute
      values are compared. All other fields are compared with their sign.
    * The filing is rounded to its units, so MATCH means |app - filing| <= 0.5 x units
      (e.g. +/- 500,000 for MILLIONS). The difference is shown in the filing's units.
    * Statuses, checked in this order: NO APP ROW, APP VALUE MISSING (never treated as 0),
      NOT CHECKED, INPUT ERROR, MATCH / MISMATCH. No difference is computed with a missing value.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.financial_normalizer import POSITIVE_FIELDS, normalize_company_facts  # noqa: E402
from src.models import (  # noqa: E402
    ALL_FIELDS,
    FIELD_GROUPS,
    FIELD_LABELS,
    CompanyFinancials,
    CompanyMatch,
    Units,
)
from src.pdf_extractor import parse_number  # noqa: E402
from src.public_data import build_company_info  # noqa: E402
from src.sec_client import SecClient, SecClientError, pad_cik  # noqa: E402

DOCS = ROOT / "docs"
APP_CSV = DOCS / "reconciliation_app_values.csv"
EXPECTED_CSV = DOCS / "reconciliation_expected.csv"
REPORT_MD = DOCS / "reconciliation.md"
CACHE_DIR = ROOT / "data" / "cache"
DEFAULT_TICKERS = ["MSFT", "AAPL"]

APP_COLUMNS = ["fetched_at", "ticker", "cik", "company_name", "fiscal_year", "period_end",
               "currency", "field", "app_value", "origin", "tag", "form", "accession",
               "filing_date", "source_url", "filing_url", "note"]
EXPECTED_COLUMNS = ["ticker", "fiscal_year", "field", "where_in_filing",
                    "filing_value_as_printed", "filing_units", "filing_url", "explanation"]

#: Figures checked by hand for the latest fiscal year of each company.
LATEST_YEAR_FIELDS = ["revenue", "ebit", "net_income", "total_assets", "current_assets",
                      "current_liabilities", "total_equity", "operating_cash_flow", "capex"]
#: One prior-year figure (comparative column of the same 10-K).
PRIOR_YEAR_FIELD = "net_income"

ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{doc}"
CONFIRM = "[confirm exact line label]"
_STATEMENTS = {"balance_sheet": "Balance sheet", "income_statement": "Income statement",
               "cash_flow": "Cash flow statement"}
_UNIT_ALIASES = {"ONES": "UNITS"}


class Status(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_CHECKED = "NOT CHECKED"
    APP_VALUE_MISSING = "APP VALUE MISSING"
    NO_APP_ROW = "NO APP ROW"
    INPUT_ERROR = "INPUT ERROR"


#: Statuses that need attention in the "Differences and interpretation" section.
ATTENTION = (Status.MISMATCH, Status.APP_VALUE_MISSING, Status.NO_APP_ROW, Status.INPUT_ERROR)


class ReconcileError(Exception):
    """A problem that stops the script (message is shown to the user)."""


# --------------------------------------------------------------------------- parsing

def parse_filing_value(text: Optional[str]) -> Optional[Decimal]:
    """Printed filing value -> Decimal in the printed units.

    Returns None for an empty cell. Raises ValueError if the text is not a number
    (e.g. "—" or "abc"); a dash shown for zero must be typed as 0.
    """
    if text is None or not str(text).strip():
        return None
    cleaned = re.sub(r"[$\s]", "", str(text))
    value = parse_number(cleaned, decimal_comma=False)
    if value is None:
        raise ValueError(f"could not read filing value {text!r} as a number "
                         "(type 0 if the filing shows a dash for zero)")
    return Decimal(str(value))


def parse_units(text: Optional[str]) -> Units:
    """filing_units -> Units. Accepts Units names (case-insensitive) and "ones".

    Raises ValueError if empty or unknown.
    """
    name = (text or "").strip().upper()
    name = _UNIT_ALIASES.get(name, name)
    if name not in Units.__members__:
        raise ValueError(f"unknown filing_units {text!r} (use UNITS/ONES, THOUSANDS, "
                         "MILLIONS or BILLIONS)")
    return Units[name]


def parse_app_value(text: Optional[str]) -> Optional[Decimal]:
    """App value from the CSV (full units) -> Decimal, or None if the cell is empty."""
    if text is None or not str(text).strip():
        return None
    try:
        return Decimal(str(text).strip())
    except InvalidOperation:
        raise ValueError(f"app_value {text!r} in the app CSV is not a number") from None


def format_app_value(value: Optional[float]) -> str:
    """Full-unit value for the CSV: exact, no rounding, empty for None."""
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


# --------------------------------------------------------------------------- SEC helpers

def accession_from_location(location: Optional[str]) -> Optional[str]:
    """'10-K accn 0000789019-24-000081' -> '0000789019-24-000081'."""
    if not location:
        return None
    match = re.search(r"accn\s+(\S+)", location)
    return match.group(1) if match else None


def form_from_location(location: Optional[str]) -> Optional[str]:
    """'10-K accn ...' -> '10-K'."""
    if not location:
        return None
    match = re.match(r"\s*(\S+)\s+accn\b", location)
    return match.group(1) if match else None


def filing_index(submissions: dict) -> dict[str, dict[str, str]]:
    """Accession number -> {primaryDocument, form, filingDate, reportDate} from filings.recent."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    columns = {key: recent.get(key) or []
               for key in ("primaryDocument", "form", "filingDate", "reportDate")}
    index: dict[str, dict[str, str]] = {}
    for i, accn in enumerate(recent.get("accessionNumber") or []):
        index[accn] = {key: str(col[i]) if i < len(col) else "" for key, col in columns.items()}
    return index


def build_filing_url(cik: str, accession: str, primary_document: str) -> str:
    """Link to the filing's main document in the EDGAR archive."""
    return ARCHIVES_URL.format(cik=int(pad_cik(cik)), accn=accession.replace("-", ""),
                               doc=primary_document)


def filing_url_for(cik: str, accession: Optional[str],
                   filings: dict[str, dict[str, str]]) -> str:
    """Filing URL for an accession, or "" if it is not in submissions filings.recent."""
    if not accession:
        return ""
    doc = (filings.get(accession) or {}).get("primaryDocument")
    return build_filing_url(cik, accession, doc) if doc else ""


def lookup_ticker(tickers_json: dict, ticker: str) -> tuple[str, str]:
    """Exact (case-insensitive) ticker -> (10-digit CIK, SEC title). No fuzzy matching."""
    wanted = ticker.strip().upper()
    hits = [e for e in tickers_json.values()
            if isinstance(e, dict) and str(e.get("ticker", "")).upper() == wanted]
    ciks = {pad_cik(e["cik_str"]) for e in hits}
    if not ciks:
        raise ReconcileError(f"Ticker {ticker!r} not found in the SEC ticker list.")
    if len(ciks) > 1:
        raise ReconcileError(f"Ticker {ticker!r} maps to several CIKs {sorted(ciks)}; "
                             "refusing to guess.")
    return ciks.pop(), str(hits[0]["title"])


# --------------------------------------------------------------------------- fetch

@dataclass
class CompanyFetch:
    """Everything fetched and derived for one ticker."""
    ticker: str
    cik: str
    financials: CompanyFinancials
    filings: dict[str, dict[str, str]]

    @property
    def latest_accession(self) -> Optional[str]:
        """Accession of the latest period's net income (the latest 10-K the app used)."""
        latest = self.financials.latest()
        prov = latest.net_income.provenance if latest else None
        return accession_from_location(prov.location if prov else None)

    @property
    def latest_filing_url(self) -> str:
        return filing_url_for(self.cik, self.latest_accession, self.filings)


def fetch_company(client: Any, tickers_json: dict, ticker: str) -> CompanyFetch:
    """Fetch and normalise one company exactly as the app does."""
    cik, title = lookup_ticker(tickers_json, ticker)
    submissions = client.get_submissions(cik)
    info = build_company_info(CompanyMatch(name=title, ticker=ticker.upper(), cik=cik),
                              cik, submissions)
    facts = client.get_company_facts(cik)
    financials = normalize_company_facts(facts, info, max_periods=3)
    if not financials.periods:
        raise ReconcileError(f"{ticker}: no annual periods found by the normalizer "
                             f"({' '.join(financials.warnings)})")
    return CompanyFetch(ticker=ticker.upper(), cik=cik, financials=financials,
                        filings=filing_index(submissions))


def app_rows(cf: CompanyFetch, fetched_at: str) -> list[dict[str, str]]:
    """One CSV row per period x field (missing values -> empty app_value)."""
    rows: list[dict[str, str]] = []
    for period in cf.financials.periods:
        for field in ALL_FIELDS:
            fv = getattr(period, field)
            prov = fv.provenance
            accn = accession_from_location(prov.location if prov else None)
            rows.append({
                "fetched_at": fetched_at, "ticker": cf.ticker, "cik": cf.cik,
                "company_name": cf.financials.company.name,
                "fiscal_year": str(period.fiscal_year),
                "period_end": period.period_end.isoformat() if period.period_end else "",
                "currency": period.currency, "field": field,
                "app_value": format_app_value(fv.value),
                "origin": prov.origin.value if prov else "",
                "tag": (prov.tag or "") if prov else "",
                "form": form_from_location(prov.location if prov else None) or "",
                "accession": accn or "",
                "filing_date": prov.filing_date.isoformat() if prov and prov.filing_date else "",
                "source_url": prov.source_ref if prov else "",
                "filing_url": filing_url_for(cf.cik, accn, cf.filings),
                "note": (prov.note or "") if prov else "",
            })
    return rows


def where_in_filing(field: str, prior_year: bool = False) -> str:
    """Statement + generic line label; Person 2 replaces it with the exact printed label."""
    group = next(g for g, fields in FIELD_GROUPS.items() if field in fields)
    statement = _STATEMENTS[group]
    if prior_year:
        statement += ", prior-year comparative column"
    return f"{statement} — {FIELD_LABELS[field]} {CONFIRM}"


def template_rows(cf: CompanyFetch) -> list[dict[str, str]]:
    """Expected-CSV rows: 9 latest-year figures + prior-year net income, values EMPTY."""
    latest_year = cf.financials.periods[0].fiscal_year
    keys = [(latest_year, f, False) for f in LATEST_YEAR_FIELDS]
    if len(cf.financials.periods) >= 2:
        keys.append((cf.financials.periods[1].fiscal_year, PRIOR_YEAR_FIELD, True))
    return [{"ticker": cf.ticker, "fiscal_year": str(year), "field": field,
             "where_in_filing": where_in_filing(field, prior),
             "filing_value_as_printed": "", "filing_units": "",
             "filing_url": cf.latest_filing_url, "explanation": ""}
            for year, field, prior in keys]


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ReconcileError(f"{path} does not exist.")
    with open(path, newline="", encoding="utf-8") as fh:
        return [{k: (v or "") for k, v in row.items() if k is not None}
                for row in csv.DictReader(fh)]


def fetch_all(tickers: list[str], client: Any) -> list[CompanyFetch]:
    """Fetch every ticker; any failure raises (so nothing is written)."""
    tickers_json = client.get_company_tickers()
    results = []
    for ticker in tickers:
        try:
            results.append(fetch_company(client, tickers_json, ticker))
        except SecClientError as exc:
            raise ReconcileError(f"{ticker}: SEC request failed: {exc.message}") from None
    return results


def lookup_list(cf: CompanyFetch) -> str:
    """Plain-text list of the figures Person 2 must look up for one company."""
    accn = cf.latest_accession or "?"
    info = cf.filings.get(accn, {})
    lines = [f"{cf.ticker} — {cf.financials.company.name} (CIK {cf.cik})",
             f"  10-K accession : {accn}",
             f"  form / filed   : {info.get('form', '?')} / {info.get('filingDate', '?')}",
             f"  period end     : {info.get('reportDate', '?')}",
             f"  filing_url     : {cf.latest_filing_url or '(not found in submissions)'}",
             "  look up:"]
    for row in template_rows(cf):
        lines.append(f"    FY{row['fiscal_year']}  {row['field']:<20} {row['where_in_filing']}")
    return "\n".join(lines)


def run_fetch(tickers: list[str], client: Any, app_csv: Path = APP_CSV,
              expected_csv: Path = EXPECTED_CSV, now: Callable[[], datetime] | None = None,
              out: Callable[[str], None] = print) -> list[CompanyFetch]:
    """FETCH mode: write the app-values CSV and (only if missing) the expected template."""
    fetched_at = (now or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds")
    companies = fetch_all(tickers, client)
    write_csv(app_csv, APP_COLUMNS, [r for cf in companies for r in app_rows(cf, fetched_at)])
    out(f"Wrote {app_csv} (fetched_at {fetched_at}).")
    if expected_csv.exists():
        out(f"{expected_csv} already exists: left untouched (your typed values are kept).")
    else:
        write_csv(expected_csv, EXPECTED_COLUMNS,
                  [r for cf in companies for r in template_rows(cf)])
        out(f"Created template {expected_csv} (filing values EMPTY, to be typed by hand).")
    for cf in companies:
        out("")
        out(lookup_list(cf))
    return companies


# --------------------------------------------------------------------------- compare

@dataclass
class Comparison:
    """Result for one expected row."""
    expected: dict[str, str]
    app: Optional[dict[str, str]]
    status: Status
    app_value: Optional[Decimal] = None
    filing_value: Optional[Decimal] = None      # full units, signed as printed
    units: Optional[Units] = None
    difference: Optional[Decimal] = None        # full units, after the abs rule
    error: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        e = self.expected
        return e.get("ticker", ""), e.get("fiscal_year", ""), e.get("field", "")


def _key(row: dict[str, str]) -> tuple[str, Optional[int], str]:
    try:
        year: Optional[int] = int(str(row.get("fiscal_year", "")).strip())
    except ValueError:
        year = None
    return (str(row.get("ticker", "")).strip().upper(), year,
            str(row.get("field", "")).strip())


def tolerance(units: Units) -> Decimal:
    """Half of one printed unit (the filing is rounded to its units)."""
    return Decimal(units.value) / 2


def compare_row(expected: dict[str, str], app: Optional[dict[str, str]]) -> Comparison:
    """Compare one expected row with its app row (see module docstring for the rules)."""
    if app is None:
        return Comparison(expected, None, Status.NO_APP_ROW)
    try:
        app_value = parse_app_value(app.get("app_value"))
    except ValueError as exc:
        return Comparison(expected, app, Status.INPUT_ERROR, error=str(exc))
    if app_value is None:
        return Comparison(expected, app, Status.APP_VALUE_MISSING)
    try:
        printed = parse_filing_value(expected.get("filing_value_as_printed"))
    except ValueError as exc:
        return Comparison(expected, app, Status.INPUT_ERROR, app_value=app_value, error=str(exc))
    if printed is None:
        return Comparison(expected, app, Status.NOT_CHECKED, app_value=app_value)
    try:
        units = parse_units(expected.get("filing_units"))
    except ValueError as exc:
        return Comparison(expected, app, Status.INPUT_ERROR, app_value=app_value, error=str(exc))
    filing_value = printed * Decimal(units.value)
    a, f = app_value, filing_value
    if _key(expected)[2] in POSITIVE_FIELDS:
        a, f = abs(a), abs(f)
    difference = a - f
    status = Status.MATCH if abs(difference) <= tolerance(units) else Status.MISMATCH
    return Comparison(expected, app, status, app_value=app_value, filing_value=filing_value,
                      units=units, difference=difference)


def compare(expected_rows: list[dict[str, str]],
            app_rows_: list[dict[str, str]]) -> list[Comparison]:
    """Compare every expected row; a bad or duplicate key gives INPUT ERROR."""
    app_by_key = {_key(r): r for r in app_rows_}
    seen: set[tuple] = set()
    results = []
    for row in expected_rows:
        key = _key(row)
        if key[1] is None:
            results.append(Comparison(row, None, Status.INPUT_ERROR,
                                      error=f"fiscal_year {row.get('fiscal_year')!r} is not a year"))
            continue
        if key in seen:
            results.append(Comparison(row, None, Status.INPUT_ERROR,
                                      error="duplicate row (same ticker, fiscal_year, field)"))
            continue
        seen.add(key)
        results.append(compare_row(row, app_by_key.get(key)))
    return results


# --------------------------------------------------------------------------- markdown

def _fmt_num(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    return format(value.normalize(), ",f") if value != value.to_integral() else f"{int(value):,}"


def _fmt_diff(c: Comparison) -> str:
    if c.difference is None or c.units is None:
        return "—"
    in_units = (c.difference / Decimal(c.units.value)).normalize()
    return f"{format(in_units, '+,f')} {c.units.name.lower()}"


def _fmt_filing(c: Comparison) -> str:
    printed = c.expected.get("filing_value_as_printed", "").strip()
    if not printed:
        return "—"
    units = c.expected.get("filing_units", "").strip()
    full = f" = {_fmt_num(c.filing_value)}" if c.filing_value is not None else ""
    return f"{printed} ({units or 'units?'}){full}"


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _company_section(ticker: str, comps: list[Comparison],
                     app_rows_: list[dict[str, str]]) -> list[str]:
    company_rows = [r for r in app_rows_ if r.get("ticker", "").upper() == ticker]
    name = company_rows[0].get("company_name", "") if company_rows else ""
    cik = company_rows[0].get("cik", "") if company_rows else ""
    currency = sorted({r.get("currency", "") for r in company_rows} - {""})
    urls = sorted({c.expected.get("filing_url", "") for c in comps} - {""})
    lines = [f"## {ticker} — {name}".rstrip(" —"), ""]
    if cik:
        lines.append(f"- CIK: {cik}")
    if currency:
        lines.append(f"- Currency: {', '.join(currency)} (app values in full units)")
    for url in urls:
        lines.append(f"- 10-K document: {url}")
    lines += ["", "| Field | FY | App value | Filing value (as printed) | Difference | Status "
                  "| Tag | Accession | Where in filing |",
              "|---|---|---:|---|---:|---|---|---|---|"]
    for c in comps:
        app = c.app or {}
        lines.append("| " + " | ".join(_cell(x) for x in [
            c.expected.get("field", ""), c.expected.get("fiscal_year", ""),
            _fmt_num(c.app_value), _fmt_filing(c), _fmt_diff(c), f"**{c.status.value}**",
            app.get("tag", "") or "—", app.get("accession", "") or "—",
            c.expected.get("where_in_filing", "")]) + " |")
    counts = {s: sum(1 for c in comps if c.status == s) for s in Status}
    lines += ["", "Status count: " + ", ".join(f"{s.value} {n}" for s, n in counts.items() if n),
              "", "### Differences and interpretation", ""]
    flagged = [c for c in comps if c.status in ATTENTION]
    if not flagged:
        lines.append("No mismatches, missing app values or input errors in the rows checked.")
    for c in flagged:
        app = c.app or {}
        ticker_, year, field = c.key
        lines.append(f"- **{field} FY{year} — {c.status.value}**")
        if c.status == Status.MISMATCH:
            lines.append(f"  - App {_fmt_num(c.app_value)} vs filing {_fmt_filing(c)}; "
                         f"difference {_fmt_diff(c)} (tolerance ±0.5 "
                         f"{c.units.name.lower() if c.units else 'unit'}).")
        if c.error:
            lines.append(f"  - Input problem: {_cell(c.error)}")
        if app:
            lines.append(f"  - Provenance: tag `{app.get('tag') or '—'}`, origin "
                         f"{app.get('origin') or '—'}, {app.get('form') or '?'} accn "
                         f"{app.get('accession') or '—'}, filed {app.get('filing_date') or '—'}")
            if app.get("note"):
                lines.append(f"  - Normalizer note: {_cell(app['note'])}")
        explanation = c.expected.get("explanation", "").strip()
        lines.append(f"  - Explanation: {_cell(explanation) if explanation else '**EXPLANATION NEEDED**'}")
    lines.append("")
    return lines


def render_markdown(comps: list[Comparison], app_rows_: list[dict[str, str]],
                    compared_at: str) -> str:
    """docs/reconciliation.md, generated entirely from the two CSVs."""
    fetched = sorted({r.get("fetched_at", "") for r in app_rows_} - {""})
    sources = sorted({r.get("source_url", "") for r in app_rows_} - {""})
    lines = [
        "# Reconciliation: app values vs official 10-K filings",
        "",
        "> Generated by `scripts/reconcile.py --compare` from `docs/reconciliation_app_values.csv`"
        " and `docs/reconciliation_expected.csv`. Do not edit by hand: explanations live in the"
        " `explanation` column of the expected CSV.",
        "",
        f"- App values fetched (UTC): {', '.join(fetched) or 'unknown'}",
        f"- Comparison run (UTC): {compared_at}",
        "- App values: SEC EDGAR XBRL company facts, normalised by "
        "`src/financial_normalizer.py` (the same code the app uses).",
        "- Filing values: **typed by hand by Person 2 from the official 10-K** (document link "
        "per company below).",
    ]
    for url in sources:
        lines.append(f"- Source: {url}")
    lines += [
        "",
        "## Rules",
        "",
        "- Filing values are parsed as printed (`(x)` = negative; commas, `$` and spaces "
        "removed) and multiplied by the statement units. A dash shown for zero is typed as 0.",
        "- Match tolerance: the filing is rounded to its units, so MATCH means "
        "|app − filing| ≤ 0.5 × units (e.g. ±500,000 for millions). Differences are shown in "
        "the filing's units.",
        "- `capex` and `interest_expense` are stored as positive amounts by the app, so their "
        "absolute values are compared. All other fields are compared with their sign.",
        "- Statuses: MATCH, MISMATCH, NOT CHECKED (no filing value typed yet), "
        "APP VALUE MISSING (the app has no value; never treated as 0), NO APP ROW (no app row "
        "for that ticker/year/field), INPUT ERROR (filing value or units unreadable).",
        "",
    ]
    tickers: list[str] = []
    for c in comps:
        t = c.key[0].upper()
        if t not in tickers:
            tickers.append(t)
    for ticker in tickers:
        lines += _company_section(ticker, [c for c in comps if c.key[0].upper() == ticker],
                                  app_rows_)
    return "\n".join(lines).rstrip() + "\n"


def run_compare(app_csv: Path = APP_CSV, expected_csv: Path = EXPECTED_CSV,
                md_path: Path = REPORT_MD, now: Callable[[], datetime] | None = None,
                out: Callable[[str], None] = print) -> list[Comparison]:
    """COMPARE mode: read the two CSVs (no network) and write the markdown report."""
    app = read_csv(app_csv)
    expected = read_csv(expected_csv)
    compared_at = (now or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds")
    comps = compare(expected, app)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(comps, app, compared_at), encoding="utf-8")
    counts = {s.value: sum(1 for c in comps if c.status == s) for s in Status}
    out(f"Wrote {md_path}: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v))
    return comps


# --------------------------------------------------------------------------- CLI

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--compare", action="store_true",
                        help="compare the saved CSVs (no network) and write the report")
    parser.add_argument("--app-csv", type=Path, default=APP_CSV)
    parser.add_argument("--expected-csv", type=Path, default=EXPECTED_CSV)
    parser.add_argument("--md", type=Path, default=REPORT_MD)
    args = parser.parse_args(argv)
    try:
        if args.compare:
            run_compare(args.app_csv, args.expected_csv, args.md)
        else:
            run_fetch(args.tickers, SecClient(cache_dir=str(CACHE_DIR)),
                      args.app_csv, args.expected_csv)
    except (ReconcileError, SecClientError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
