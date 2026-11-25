"""Owned by Person 3: manual entry table <-> CompanyFinancials, JSON save/load.

The "table" used by the Manual Entry page (and later by the PDF confirmation step) is a
pandas DataFrame with:
  - index      = ALL_FIELDS (the field keys from src/models.py), in statement order
  - "Line item"= readable label from FIELD_LABELS (display only, read-only in the UI)
  - one column per fiscal year, named with the year as a string ("2024"), newest first

Cells hold whatever the analyst typed (a number, a string such as "(1,234)", or nothing).
Values in the table are in the REPORTING UNITS the analyst selected (e.g. millions);
table_to_financials multiplies them so the shared model always stores FULL currency units.

Key rule: a blank cell is MISSING (None). Only a typed 0 is a real zero.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

import pandas as pd

from src.models import (ALL_FIELDS, FIELD_GROUPS, FIELD_LABELS, CompanyFinancials,
                        CompanyInfo, FinancialPeriod, FinancialValue, Provenance, SourceType,
                        Units, ValueOrigin, VerificationStatus)

LINE_ITEM_COL = "Line item"

# Text the analyst may type to mean "I don't have this value" -> missing (None).
_MISSING_TOKENS = {"", "-", "—", "–", "n/a", "na", "nan", "none", "null"}
# Characters ignored inside a number: spaces (incl. non-breaking/thin), Swiss apostrophes,
# currency symbols. Letters are NOT ignored, so "12abc" is unreadable rather than guessed.
_IGNORED_CHARS = re.compile(r"[\s  '’$€£]")
_US_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")    # 1,234,567.89
_EU_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")    # 1.234.567,89
_PLAIN = re.compile(r"^\d+(\.\d+)?$|^\.\d+$")               # 1234.5 or .5
_DECIMAL_COMMA = re.compile(r"^\d+,\d+$")                   # 1234,5 (no thousands sep)

# Which ratios need which inputs (mirrors the formulas in the shared contract; used only to
# tell the analyst what a blank field will block). EBITDA can come from EBIT + D&A instead.
RATIO_INPUTS: dict[str, list[str]] = {
    "Current Ratio": ["current_assets", "current_liabilities"],
    "Cash Ratio": ["cash", "current_liabilities"],
    "Working Capital": ["current_assets", "current_liabilities"],
    "Total Debt": ["short_term_debt", "long_term_debt"],
    "Debt-to-Equity": ["short_term_debt", "long_term_debt", "total_equity"],
    "Debt-to-Assets": ["short_term_debt", "long_term_debt", "total_assets"],
    "Net Debt": ["short_term_debt", "long_term_debt", "cash"],
    "Net Debt / EBITDA": ["short_term_debt", "long_term_debt", "cash", "ebitda"],
    "Operating Margin": ["ebit", "revenue"],
    "Net Profit Margin": ["net_income", "revenue"],
    "Return on Assets": ["net_income", "total_assets"],
    "Interest Coverage": ["ebit", "interest_expense"],
    "Free Cash Flow": ["operating_cash_flow", "capex"],
    "FCF Margin": ["operating_cash_flow", "capex", "revenue"],
    "Revenue Growth": ["revenue"],  # also needs the previous year's revenue
}


# --------------------------------------------------------------------------------------
# Parsing a single cell
# --------------------------------------------------------------------------------------
def is_blank(value: Any) -> bool:
    """True if the cell means "missing": None, NaN, empty text, "-", "n/a" ..."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip().lower() in _MISSING_TOKENS:
        return True
    return False


def parse_cell(value: Any) -> Optional[float]:
    """Turn one table cell into a float, or None if it is blank OR unreadable.

    Accepted: numbers; "1,234.5" (US); "1.234,5" (European); "1 234" ; "1'234";
    "(1,234)" or "-1,234" (negative); "1234,5" (decimal comma); "$1,234".
    Missing: None, NaN, "", "-", "—", "n/a".
    Ambiguity rules (documented so they can be defended):
      - "1,234" (one comma + exactly 3 digits) is read as 1234 (thousands separator).
      - "1.234" (one dot) is read as 1.234 (decimal point), like Python and most US
        software. A European "1.234" meaning 1234 should be typed "1234" or "1.234,0".
    Text that is not a number (e.g. "12abc", "about 5") returns None: we never guess.
    Use is_blank() to tell "blank" from "unreadable".
    """
    if isinstance(value, bool):          # True/False is not a financial figure
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return None if math.isnan(v) or math.isinf(v) else v
    if is_blank(value) or not isinstance(value, str):
        return None

    text = _IGNORED_CHARS.sub("", value.strip())
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    elif text.startswith("+"):
        text = text[1:]
    if not text:
        return None

    if _US_THOUSANDS.match(text):
        number = float(text.replace(",", ""))
    elif _EU_THOUSANDS.match(text) and (text.count(".") >= 2 or "," in text):
        # European: "1.234,5" or "1.234.567". A lone "1.234" falls through to _PLAIN.
        number = float(text.replace(".", "").replace(",", "."))
    elif _PLAIN.match(text):
        number = float(text)
    elif _DECIMAL_COMMA.match(text):
        number = float(text.replace(",", "."))
    else:
        return None
    return -number if negative else number


def is_unreadable(value: Any) -> bool:
    """True if the analyst typed something that is neither blank nor a number."""
    return not is_blank(value) and parse_cell(value) is None


# --------------------------------------------------------------------------------------
# Table helpers
# --------------------------------------------------------------------------------------
def year_columns(df: pd.DataFrame) -> list[str]:
    """The fiscal-year columns of a table (column names that are 4-digit years)."""
    return [c for c in df.columns if re.fullmatch(r"\d{4}", str(c))]


def empty_table(years: list[int]) -> pd.DataFrame:
    """Blank entry table: rows = ALL_FIELDS, a "Line item" column, one column per year.

    Years are sorted newest first and used as string column names. Every value is
    missing (None), never 0.
    """
    cols = [str(y) for y in sorted(set(years), reverse=True)]
    df = pd.DataFrame(index=pd.Index(ALL_FIELDS, name="field"))
    df[LINE_ITEM_COL] = [FIELD_LABELS[f] for f in ALL_FIELDS]
    for c in cols:
        df[c] = pd.Series([None] * len(ALL_FIELDS), index=df.index, dtype="object")
    return df


def resize_table(df: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Return a table for `years`, keeping values already typed for years that remain."""
    new = empty_table(years)
    for c in year_columns(new):
        if c in df.columns:
            new[c] = df[c].reindex(new.index).astype("object")
    return new


def unreadable_cells(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """List (field, year, raw text) for every cell that could not be read as a number."""
    out = []
    for c in year_columns(df):
        for field in ALL_FIELDS:
            raw = df.at[field, c] if field in df.index else None
            if is_unreadable(raw):
                out.append((field, c, str(raw)))
    return out


def table_to_financials(df: pd.DataFrame, company_name: str, currency: str, units: Units,
                        source_type: SourceType, source_ref: str) -> CompanyFinancials:
    """Convert a confirmed table into CompanyFinancials (full currency units).

    - Each cell is multiplied by units.value (a "1,234" in millions -> 1_234_000_000.0).
    - Blank -> None (missing). A typed 0 -> 0.0 (a real zero). Unreadable text -> None AND
      a warning in CompanyFinancials.warnings, so it is never used silently.
    - Provenance: origin MANUAL for manual entry, REPORTED for PDF (the analyst confirmed a
      figure that came from a document); verification USER_CONFIRMED in both cases.
    - A year column with no value at all is skipped (no empty period is created).
    - Periods are sorted newest first; currency is kept as given, never converted.
    """
    origin = ValueOrigin.MANUAL if source_type == SourceType.MANUAL else ValueOrigin.REPORTED
    periods: list[FinancialPeriod] = []
    warnings: list[str] = []

    for col in sorted(year_columns(df), key=int, reverse=True):
        fy = int(col)
        values: dict[str, FinancialValue] = {}
        for field in ALL_FIELDS:
            raw = df.at[field, col] if field in df.index else None
            number = parse_cell(raw)
            if number is None:
                if is_unreadable(raw):
                    warnings.append(f"FY{fy} {FIELD_LABELS[field]}: could not read "
                                    f"'{raw}' as a number, so it is treated as missing.")
                continue
            values[field] = FinancialValue(
                value=number * units.value,
                provenance=Provenance(
                    source_type=source_type,
                    source_ref=source_ref,
                    original_text=None if isinstance(raw, (int, float)) else str(raw),
                    origin=origin,
                    verification=VerificationStatus.USER_CONFIRMED,
                    note=f"Entered in {units.name.lower()} of {currency}",
                ),
            )
        if not values:
            continue  # completely empty year column
        periods.append(FinancialPeriod(fiscal_year=fy, is_annual=True, currency=currency,
                                       original_units=units, **values))

    return CompanyFinancials(
        company=CompanyInfo(name=company_name.strip() or "Unnamed company"),
        source_type=source_type,
        periods=periods,
        warnings=warnings,
    )


def _display_number(v: Optional[float]) -> Optional[str]:
    """Format a float for the editable table without scientific notation or '.0'."""
    if v is None:
        return None
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def financials_to_table(f: CompanyFinancials) -> tuple[pd.DataFrame, str, Units]:
    """Inverse of table_to_financials, used to load a saved session back into the form.

    Values are divided back into each period's original units. Returns (table, currency,
    units) taken from the newest period (UNITS / USD if there are no periods).
    """
    latest = f.latest()
    units = latest.original_units if latest else Units.UNITS
    currency = latest.currency if latest else "USD"
    df = empty_table([p.fiscal_year for p in f.periods])
    for p in f.periods:
        for field in ALL_FIELDS:
            v = p.get(field)
            if v is not None:
                df.at[field, str(p.fiscal_year)] = _display_number(v / units.value)
    return df, currency, units


# --------------------------------------------------------------------------------------
# Missing data -> ratios that cannot be computed
# --------------------------------------------------------------------------------------
def blocked_ratios(f: CompanyFinancials) -> dict[int, dict[str, list[str]]]:
    """For each fiscal year: ratio label -> readable labels of the missing inputs.

    Mirrors the shared formulas: total debt needs BOTH debt components; EBITDA counts as
    available if reported, or if EBIT and D&A are both present; revenue growth also needs
    the previous fiscal year's revenue. Only lists ratios that are blocked.
    """
    out: dict[int, dict[str, list[str]]] = {}
    for p in f.periods:
        blocked: dict[str, list[str]] = {}
        for ratio, fields in RATIO_INPUTS.items():
            missing = []
            for field in fields:
                if field == "ebitda":
                    if p.get("ebitda") is None and (p.get("ebit") is None or
                                                    p.get("depreciation_amortization") is None):
                        missing.append("EBITDA (or EBIT and D&A)")
                elif p.get(field) is None:
                    missing.append(FIELD_LABELS[field])
            if ratio == "Revenue Growth":
                prev = f.period(p.fiscal_year - 1)
                if prev is None or prev.get("revenue") is None:
                    missing.append(f"Revenue for FY{p.fiscal_year - 1}")
            if missing:
                blocked[ratio] = missing
        out[p.fiscal_year] = blocked
    return out


def section_of(field: str) -> str:
    """'balance_sheet' / 'income_statement' / 'cash_flow' for a field key."""
    return next(g for g, fields in FIELD_GROUPS.items() if field in fields)


# --------------------------------------------------------------------------------------
# Save / load a working session (downloaded by the analyst; nothing stored on the server)
# --------------------------------------------------------------------------------------
def financials_to_json(f: CompanyFinancials) -> str:
    """Serialise for the 'save my working session' download."""
    return f.model_dump_json(indent=2)


def financials_from_json(s: str) -> CompanyFinancials:
    """Load a previously saved working session (raises pydantic.ValidationError if invalid)."""
    return CompanyFinancials.model_validate_json(s)
