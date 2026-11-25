"""Owned by Person 3: local, deterministic extraction of financial figures from PDFs.

No AI, no external service, nothing written to disk, nothing from the document logged.
Everything happens in memory on the bytes the analyst uploaded.

How it works, in plain English:
 1. Check each file is a real, readable PDF of at most 20 MB.
 2. Read the words on each page with their positions and rebuild the visual rows,
    so a label and the numbers printed to its right end up on the same line.
 3. Detect reporting units ("in millions", "en milliers"...), currency and the year
    column headers ("2024  2023").
 4. For each row whose label matches a known line item (English or French), read the
    numbers on that row and give them to the year columns from left to right.
 5. Anything uncertain is marked "ambiguous" with a note, never chosen silently.
 6. The analyst then reviews and corrects everything in the confirmation table.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from io import BytesIO
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field

try:                                   # PyMuPDF's new import name; `fitz` is the old one
    import pymupdf as fitz
except ImportError:                    # pragma: no cover
    import fitz  # type: ignore

from src.manual_input import _display_number, empty_table, parse_cell
from src.models import Units

MAX_FILE_BYTES = 20 * 1024 * 1024
MIN_CHARS_PER_PAGE = 50
YEAR_MIN, YEAR_MAX = 2000, 2035
SCANNED_MESSAGE = ("This PDF looks scanned (image only). Text could not be read reliably. "
                   "Please enter the figures manually.")
UNITS_WARNING = "Reporting units not detected; please select them before confirming."
# Stored as positive amounts by the shared sign convention, even when a statement prints
# them in brackets as a cash outflow, e.g. "(1,234)".
# Cost of revenue and D&A are expenses too: gross profit = revenue - cost of revenue only
# holds if cost of revenue is stored positive (as SEC data stores it).
POSITIVE_FIELDS = {"capex", "interest_expense", "cost_of_revenue", "depreciation_amortization"}


# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------
class ExtractedItem(BaseModel):
    field: str                         # one of ALL_FIELDS
    fiscal_year: int
    value: Optional[float] = None      # FULL units if units were detected, else raw number
    original_text: str
    source_file: str
    page: int                          # 1-based
    matched_label: str
    status: Literal["ok", "ambiguous"] = "ok"
    note: str = ""


class PdfExtractionResult(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)
    fiscal_years: list[int] = Field(default_factory=list)       # newest first
    currency: Optional[str] = None
    units: Optional[Units] = None
    warnings: list[str] = Field(default_factory=list)
    scanned_files: list[str] = Field(default_factory=list)
    failed_files: list[str] = Field(default_factory=list)       # "name: reason"


# --------------------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------------------
def normalise(text: str) -> str:
    """Lowercase, remove accents, unify apostrophes and collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("‘", "'").lower()
    return re.sub(r"\s+", " ", text).strip()


def parse_number(text: str, decimal_comma: Optional[bool] = None) -> Optional[float]:
    """'1,234' '1 234' '1.234,56' '(1,234)' '-1,234' '1,234-' -> float; '—' '-' 'n/a' -> None.

    Same rules as manual entry (src.manual_input.parse_cell) plus a trailing minus sign.
    `decimal_comma` is the document's number style when known: True for European
    ("4.000" = four thousand, "1,5" = one and a half), False for US/UK ("1,500" = fifteen
    hundred). None = unknown: the manual-entry rules apply. Non-numbers return None.
    """
    if text is None:
        return None
    t = str(text).strip().replace("−", "-").replace("–", "-")
    negative = False
    if re.fullmatch(r"[\d.,'\s\u00a0\u202f]+-", t):        # trailing minus: "1,234-"
        negative, t = True, t[:-1]
    if decimal_comma is not None:
        m = re.fullmatch(r"(\(?-?)([\d.,'\s\u00a0\u202f]*\d)(\)?)", t)
        if m:
            core = re.sub(r"[\s'\u00a0\u202f]", "", m.group(2))
            core = core.replace(".", "").replace(",", ".") if decimal_comma \
                else core.replace(",", "")
            if core.count(".") > 1:
                return None
            t = m.group(1) + core + m.group(3)
    value = parse_cell(t)
    return -value if negative and value is not None else value


def detect_number_style(text: str) -> Optional[bool]:
    """True if numbers use a decimal comma (European), False if a decimal point (US/UK),
    None if the text gives no clear signal or mixed signals."""
    eu = len(re.findall(r"\d\.\d{3},\d|(?<![\d.,])\d+,\d{1,2}(?![\d.,])", text))
    us = len(re.findall(r"\d,\d{3}\.\d|(?<![\d.,])\d+\.\d{1,2}(?![\d.,])", text))
    if eu and not us:
        return True
    if us and not eu:
        return False
    return None


_UNIT_PATTERNS: list[tuple[Units, str]] = [
    (Units.THOUSANDS, r"in thousands|thousands of|\(\s*in \S*\s*thousands|en milliers|"
                      r"milliers d|\bk\s?€|\bkeur\b|\bk\$|\$\s?k\b|\$\s?000|'000"),
    (Units.MILLIONS, r"in millions|millions of|\(\s*in \S*\s*millions|en millions|"
                     r"millions d|\bm\s?€|\bmeur\b|\bm\$|\$\s?m\b|\$\s?mn\b|\bmusd\b"),
    (Units.BILLIONS, r"in billions|billions of|en milliards|milliards d|\$\s?bn\b|"
                     r"\bbn\s?€|€\s?bn\b"),
]


def detect_units(text: str) -> Optional[Units]:
    """Reporting units stated in the text, or None if absent or contradictory."""
    t = normalise(text)
    found = {u for u, pattern in _UNIT_PATTERNS if re.search(pattern, t)}
    return found.pop() if len(found) == 1 else None


_CURRENCY_PATTERNS: dict[str, str] = {        # codes are case-sensitive, words are not
    "USD": r"US\$|\bUSD\b|\$|(?i:\bdollars?\b)",
    "EUR": r"€|\b[KkMm]?EUR\b|(?i:\beuros?\b)",
    "GBP": r"£|\bGBP\b|(?i:\bpounds? sterling\b)",
    "MAD": r"\bMAD\b|\bDH\b|(?i:\bdirhams?\b)",
}


def currencies_found(text: str) -> set[str]:
    """Every currency mentioned in the text."""
    return {code for code, pattern in _CURRENCY_PATTERNS.items() if re.search(pattern, text)}


def detect_currency(text: str) -> Optional[str]:
    """The one currency the text uses; None if none or several are found."""
    found = currencies_found(text)
    return found.pop() if len(found) == 1 else None


def _years_in(line: str) -> list[int]:
    return [int(y) for y in re.findall(r"(?<![\d.,])(20\d\d)(?![\d.,])", line)
            if YEAR_MIN <= int(y) <= YEAR_MAX]


def detect_years(text: str) -> list[int]:
    """Year column headers, in the order printed (e.g. "2024 2023" -> [2024, 2023]).

    Takes the first line containing two or more plausible years (2000-2035). If no line
    has two, a line that is only a year (single-column statement) is used.
    """
    lines = text.splitlines()
    for line in lines:
        years = _years_in(line)
        if len(years) >= 2:
            return list(dict.fromkeys(years))
    for line in lines:
        years = _years_in(line)
        if len(years) == 1 and re.fullmatch(r"\D{0,12}20\d\d\D{0,3}", line.strip()):
            return years
    return []


# --------------------------------------------------------------------------------------
# Label synonyms (English and French). Matching is done on normalised text, so accents
# and capitals do not matter.
# --------------------------------------------------------------------------------------
LABEL_MAP: dict[str, list[str]] = {
    "cash": ["cash and cash equivalents", "cash & cash equivalents", "cash and equivalents",
             "tresorerie et equivalents de tresorerie", "tresorerie",
             "disponibilites"],
    "current_assets": ["total current assets", "current assets", "total actif circulant",
                       "actif circulant", "actifs courants", "total actifs courants"],
    "total_assets": ["total assets", "total actif", "total de l'actif", "total bilan",
                     "total des actifs"],
    "current_liabilities": ["total current liabilities", "current liabilities",
                            "passifs courants", "total passifs courants",
                            "dettes a court terme", "total dettes a court terme"],
    "total_liabilities": ["total liabilities", "total passif exigible", "total des dettes",
                          "total dettes", "total passifs"],
    "short_term_debt": ["short-term debt", "short term debt", "short-term borrowings",
                        "current portion of long-term debt", "current debt",
                        "emprunts a court terme", "dettes financieres courantes",
                        "dettes financieres a court terme"],
    "long_term_debt": ["long-term debt", "long term debt", "non-current borrowings",
                       "long-term borrowings", "emprunts et dettes financieres",
                       "dettes financieres non courantes", "emprunts a long terme",
                       "dettes financieres a long terme"],
    "total_equity": ["total shareholders' equity", "total stockholders' equity",
                     "total shareholders equity", "total stockholders equity",
                     "total equity", "shareholders' equity", "stockholders' equity",
                     "total capitaux propres", "capitaux propres"],
    "revenue": ["revenue", "revenues", "net sales", "total revenue", "total revenues",
                "sales", "turnover", "chiffre d'affaires", "ventes",
                "produits des activites ordinaires"],
    "cost_of_revenue": ["cost of revenue", "cost of revenues", "cost of sales",
                        "cost of goods sold", "cout des ventes", "couts des ventes",
                        "cout des marchandises vendues"],
    "gross_profit": ["gross profit", "gross margin", "marge brute", "resultat brut"],
    "ebit": ["operating income", "operating profit", "income from operations",
             "profit from operations", "resultat d'exploitation", "resultat operationnel"],
    "ebitda": ["ebitda", "excedent brut d'exploitation"],
    "interest_expense": ["interest expense", "interest expenses", "finance costs",
                         "interest paid", "charges d'interets", "charges financieres",
                         "cout de l'endettement financier"],
    "net_income": ["net income", "net profit", "profit for the year", "net earnings",
                   "resultat net", "benefice net"],
    "depreciation_amortization": ["depreciation and amortization",
                                  "depreciation and amortisation",
                                  "depreciation & amortization", "depreciation",
                                  "dotations aux amortissements", "amortissements"],
    "operating_cash_flow": ["net cash provided by operating activities",
                            "net cash from operating activities",
                            "cash flows from operating activities",
                            "cash generated from operations", "operating cash flow",
                            "flux de tresorerie lies aux activites operationnelles",
                            "flux net de tresorerie genere par l'activite"],
    "capex": ["capital expenditures", "capital expenditure",
              "purchases of property, plant and equipment",
              "purchase of property, plant and equipment",
              "payments for property, plant and equipment",
              "acquisitions d'immobilisations corporelles",
              "acquisitions d'immobilisations", "investissements corporels"],
    "investing_cash_flow": ["net cash used in investing activities",
                            "net cash provided by (used in) investing activities",
                            "net cash from investing activities",
                            "cash flows from investing activities",
                            "flux de tresorerie lies aux activites d'investissement",
                            "flux net de tresorerie lie aux operations d'investissement"],
    "financing_cash_flow": ["net cash used in financing activities",
                            "net cash provided by (used in) financing activities",
                            "net cash from financing activities",
                            "cash flows from financing activities",
                            "flux de tresorerie lies aux activites de financement",
                            "flux net de tresorerie lie aux operations de financement"],
}
# Rows containing these words are not the line item itself (e.g. "Net income per share").
_EXCLUDE = re.compile(r"per share|par action|%|margin %|growth|attributable to non")
_SYNONYMS = sorted(((normalise(s), f) for f, ss in LABEL_MAP.items() for s in ss),
                   key=lambda x: -len(x[0]))


def match_label(label: str) -> Optional[tuple[str, str, bool]]:
    """(field, synonym, starts_line) for the best synonym, or None.

    A synonym at the start of the label beats one found inside it; among equals, the
    longest synonym wins (so "cost of revenue" beats "revenue").
    """
    text = normalise(label)
    text = re.sub(r"^([\-–•*]|\(?[a-z0-9]{1,2}[.)])\s*", "", text)   # bullets, "a)", "1."
    if not text or _EXCLUDE.search(text):
        return None
    best = None
    for synonym, field in _SYNONYMS:
        if re.match(re.escape(synonym) + r"\b", text):
            return field, synonym, True            # longest line-start match
        if best is None and re.search(r"\b" + re.escape(synonym) + r"\b", text):
            best = (field, synonym, False)
    return best


# --------------------------------------------------------------------------------------
# Reading rows from a page
# --------------------------------------------------------------------------------------
_NUMBER_TOKEN = re.compile(r"^\(?[-–−]?[\d][\d.,'  ]*\)?-?$|^[—–-]$")


def _page_rows(page) -> list[list[tuple[float, float, str]]]:
    """Words grouped into visual rows: each row is [(x0, x1, word), ...] left to right."""
    words = page.get_text("words")            # x0, y0, x1, y1, word, block, line, n
    rows: list[list] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        mid, height = (w[1] + w[3]) / 2, max(w[3] - w[1], 1)
        if rows and abs(rows[-1][0] - mid) <= height * 0.4:
            rows[-1][1].append((w[0], w[2], w[4]))
        else:
            rows.append([mid, [(w[0], w[2], w[4])]])
    return [sorted(r[1]) for r in rows]


def _split_row(row: list[tuple[float, float, str]]) -> tuple[str, list[str]]:
    """Label text (words before the first number) and the number tokens after it.

    Neighbouring numeric words are joined when the second is a 3-digit group printed
    right next to the first ("1 234" written with a space as thousands separator).
    """
    label_parts, numbers = [], []
    last_x1, height = None, 8.0
    for x0, x1, word in row:
        token = word.replace("−", "-")
        if _NUMBER_TOKEN.match(token) and (numbers or label_parts):
            if (numbers and re.fullmatch(r"\d{3}([.,]\d+)?\)?-?", token) and last_x1 is not None
                    and x0 - last_x1 < height * 0.5 and not numbers[-1].endswith(")")):
                numbers[-1] += " " + token
            else:
                numbers.append(token)
            last_x1 = x1
        elif not numbers:
            label_parts.append(word)
        else:                       # text after numbers: treat as a new label (ignored)
            break
    return " ".join(label_parts), numbers


def _clean_year_tokens(label: str, numbers: list[str]) -> list[str]:
    """Drop year headers accidentally read as values (e.g. a row "Revenue 2024")."""
    return [n for n in numbers if not (re.fullmatch(r"20\d\d", n) and
                                       YEAR_MIN <= int(n) <= YEAR_MAX)]


# --------------------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------------------
def _validate(name: str, data: bytes) -> Optional[str]:
    """Reason the file is rejected, or None if it can be opened."""
    if not name.lower().endswith(".pdf"):
        return "not a .pdf file"
    if len(data) > MAX_FILE_BYTES:
        return "larger than 20 MB"
    if not data.startswith(b"%PDF"):
        return "not a valid PDF (the file does not start with %PDF)"
    return None


def _rows_to_items(rows, years, name, page_no, decimal_comma=None) -> list[ExtractedItem]:
    items = []
    for label, numbers in rows:
        match = match_label(label)
        if match is None or not numbers:
            continue
        field, synonym, starts = match
        numbers = _clean_year_tokens(label, numbers)
        if not numbers or not years:
            continue
        notes, status = [], "ok" if starts else "ambiguous"
        if not starts:
            notes.append(f"label '{synonym}' found inside a longer line")
        if len(numbers) == len(years):
            pairs = list(zip(years, numbers))
        else:
            status = "ambiguous"
            if len(numbers) > len(years):
                notes.append(f"{len(numbers)} numbers for {len(years)} year columns; "
                             f"the last {len(years)} were used")
                pairs = list(zip(years, numbers[-len(years):]))
            else:
                notes.append(f"{len(numbers)} number(s) for {len(years)} year columns; "
                             "assigned from the left")
                pairs = list(zip(years, numbers))
        for year, token in pairs:
            value = parse_number(token, decimal_comma)
            item_notes = list(notes)
            item_status = status
            if decimal_comma is None and re.fullmatch(r"\(?-?\d{1,3}\.\d{3}\)?-?", token):
                item_status = "ambiguous"
                item_notes.append(f"'{token}' could mean {token.strip('()-')} or "
                                  f"{token.strip('()-').replace('.', '')}: number style "
                                  "of the document unclear")
            if value is not None and field in POSITIVE_FIELDS and value < 0:
                value = -value
                item_notes.append("shown as an outflow in the statement; stored as a "
                                  "positive amount (sign convention)")
            items.append(ExtractedItem(
                field=field, fiscal_year=year, value=value, original_text=token,
                source_file=name, page=page_no, matched_label=label.strip(),
                status=item_status, note="; ".join(item_notes)))
    return items


def _table_rows(data: bytes, page_index: int) -> list[tuple[str, list[str]]]:
    """Rows from pdfplumber's table detection (label cell + numeric cells)."""
    import pdfplumber
    rows = []
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            for table in pdf.pages[page_index].extract_tables() or []:
                for cells in table:
                    cells = [(c or "").strip() for c in cells]
                    if not cells or not cells[0]:
                        continue
                    nums = [c for c in cells[1:] if c and _NUMBER_TOKEN.match(c)]
                    rows.append((cells[0], nums))
    except Exception:                 # table detection is a bonus; never fail on it
        return []
    return rows


def _resolve_duplicates(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Same field and year found several times: identical values merge; different
    values are ALL kept and marked ambiguous with the pages listed. Never pick silently."""
    groups: dict[tuple[str, int], list[ExtractedItem]] = defaultdict(list)
    for it in items:
        groups[(it.field, it.fiscal_year)].append(it)
    out = []
    for group in groups.values():
        values = {it.value for it in group}
        if len(values) == 1:
            out.append(group[0])
            continue
        where = ", ".join(f"{it.source_file} p.{it.page}: {it.original_text}" for it in group)
        for it in group:
            out.append(it.model_copy(update={
                "status": "ambiguous",
                "note": "; ".join(filter(None, [it.note, f"different values found ({where})"]))}))
    return out


def extract_financials(files: list[tuple[str, bytes]]) -> PdfExtractionResult:
    """Extract candidate figures from (filename, bytes) PDF pairs, in memory only."""
    result = PdfExtractionResult()
    all_text: list[str] = []
    page_units: list[Optional[Units]] = []
    raw_items: list[ExtractedItem] = []      # values as printed (not yet multiplied)

    for name, data in files:
        reason = _validate(name, data)
        if reason is None:
            try:
                doc = fitz.open(stream=data, filetype="pdf")
            except Exception:
                reason = "the file is corrupted or cannot be opened"
        if reason:
            result.failed_files.append(f"{name}: {reason}")
            continue

        with doc:
            texts = [page.get_text("text") for page in doc]
            page_rows = [_page_rows(page) for page in doc]
            # Text rebuilt row by row, so "2024" and "2023" printed apart share a line.
            row_texts = ["\n".join(" ".join(w[2] for w in r) for r in rows)
                         for rows in page_rows]
            if doc.page_count == 0 or sum(len(t.strip()) for t in texts) / doc.page_count \
                    < MIN_CHARS_PER_PAGE:
                result.scanned_files.append(name)
                result.warnings.append(f"{name}: {SCANNED_MESSAGE}")
                continue
            doc_text = "\n".join(row_texts)
            all_text.append(doc_text)
            doc_years, doc_units = detect_years(doc_text), detect_units(doc_text)
            style = detect_number_style(doc_text)

            for i, page in enumerate(doc):
                years = detect_years(row_texts[i]) or doc_years
                page_units.append(detect_units(row_texts[i]) or doc_units)
                text_rows = [_split_row(r) for r in page_rows[i]]
                items = _rows_to_items(text_rows, years, name, i + 1, style)
                found = {(it.field, it.fiscal_year) for it in items}
                extra = [it for it in _rows_to_items(_table_rows(data, i), years, name, i + 1, style)
                         if (it.field, it.fiscal_year) not in found]
                raw_items += items + extra

    joined = "\n".join(all_text)
    # Units: only if every page agrees (or states none while others agree); otherwise the
    # analyst chooses. Values are multiplied ONLY when a single unit is known.
    known = {u for u in page_units if u is not None}
    result.units = known.pop() if len(known) == 1 else None
    if raw_items and result.units is None:
        if len(known) > 1:
            result.warnings.append("Different reporting units were found in the files; "
                                   "please check each value.")
        result.warnings.append(UNITS_WARNING)
    if result.units is not None:
        raw_items = [it.model_copy(update={"value": it.value * result.units.value})
                     if it.value is not None else it for it in raw_items]

    found_ccy = currencies_found(joined)
    result.currency = next(iter(found_ccy)) if len(found_ccy) == 1 else None
    if len(found_ccy) > 1:
        result.warnings.append("Several currencies were mentioned (" +
                               ", ".join(sorted(found_ccy)) +
                               "); please select the reporting currency.")

    result.items = _resolve_duplicates(raw_items)
    result.fiscal_years = sorted({it.fiscal_year for it in result.items}, reverse=True)
    if not result.items and all_text:
        result.warnings.append("No recognisable financial line items with year columns "
                               "were found. Please check the file or enter the figures "
                               "manually.")
    return result


# --------------------------------------------------------------------------------------
# For the confirmation table
# --------------------------------------------------------------------------------------
def result_to_table(result: PdfExtractionResult) -> tuple[pd.DataFrame,
                                                          dict[tuple[str, str], str]]:
    """Table in the empty_table format with values in the ORIGINAL reporting units,
    plus flags {(field, year): note} for every ambiguous cell.

    A cell with several conflicting candidates is left BLANK and the candidates are
    listed in its flag, so the analyst has to choose.
    """
    df = empty_table(result.fiscal_years or [])
    flags: dict[tuple[str, str], str] = {}
    divisor = result.units.value if result.units else 1
    by_cell: dict[tuple[str, str], list[ExtractedItem]] = defaultdict(list)
    for it in result.items:
        by_cell[(it.field, str(it.fiscal_year))].append(it)

    for (field, year), items in by_cell.items():
        if year not in df.columns:
            continue
        values = {it.value for it in items}
        if len(values) == 1 and items[0].value is not None:
            df.at[field, year] = _display_number(items[0].value / divisor)
        if len(values) > 1:          # conflicting candidates: blank, analyst chooses
            where = "; ".join(f"{it.original_text} ({it.source_file} p.{it.page})"
                              for it in items)
            flags[(field, year)] = f"Ambiguous: several values found: {where}"
        elif items[0].status == "ambiguous":
            flags[(field, year)] = f"Ambiguous (p.{items[0].page}): {items[0].note}"
    return df, flags
