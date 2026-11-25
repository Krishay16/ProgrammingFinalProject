"""Owned by Person 3: Manual Entry page.

The analyst types figures into three tables (balance sheet, income statement, cash flow),
validates them, can save/load a working session as a JSON file on their own computer,
and launches the analysis. Nothing is stored on the server.

Page-local widget state uses keys starting with "_p3_manual_". Shared app state
(selected company, confirmed financials, navigation) only goes through src.state.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from src import config, state
from src.data_validation import validate_financials
from src.manual_input import (blocked_ratios, dot_thousands_cells, empty_table,
                              financials_from_json, financials_to_json,
                              financials_to_table, relabel_years, resize_table,
                              table_to_financials, unreadable_cells)
from src.models import FIELD_GROUPS, FIELD_LABELS, SourceType, Units
from src.ui.confirm_table import confirm_table
from src.ui.theme import section_header

_K = "_p3_manual_"                      # prefix for this page's session keys
UNIT_OPTIONS = {"Units": Units.UNITS, "Thousands": Units.THOUSANDS,
                "Millions": Units.MILLIONS, "Billions": Units.BILLIONS}
SECTIONS = [("A. Balance Sheet", "balance_sheet"),
            ("B. Income Statement", "income_statement"),
            ("C. Cash Flow Statement", "cash_flow")]
BLANK_HINT = "Leave a field blank if you don't know it. Blank is treated as missing, not zero."
DOT_HINT = ("A number like 1.234 is read as one point two three four. For one thousand two "
            "hundred and thirty-four, type 1234 or 1,234.")
SIGN_HINT = ("Enter capital expenditures and interest expense as positive amounts (the size "
             "of the outflow or expense). Losses and net cash outflows are negative, e.g. "
             "(1,234) or -1234.")


def _init() -> None:
    ss = st.session_state
    ss.setdefault(_K + "latest_year", date.today().year - 1)
    ss.setdefault(_K + "n_years", 1)
    ss.setdefault(_K + "show_validation", False)
    selected = state.get_selected_company()
    ss.setdefault(_K + "company", selected.name if selected else "")
    ss.setdefault(_K + "currency", config.CURRENCIES[0])
    ss.setdefault(_K + "units", "Millions")
    if _K + "base" not in ss:
        _set_base(empty_table(_years()))
    # Values from a loaded session are applied here, BEFORE the widgets are created.
    pending = ss.pop(_K + "pending", None)
    if pending:
        ss.update(pending)


def _years() -> list[int]:
    ss = st.session_state
    latest = int(ss[_K + "latest_year"])
    return [latest - i for i in range(int(ss[_K + "n_years"]))]


def _set_base(df: pd.DataFrame) -> None:
    """Replace the table the editors start from (on start, clear, load, resize).

    The editors keep the analyst's edits themselves; we never feed their output back
    into them, because doing that made earlier edits disappear (found in browser testing).
    """
    ss = st.session_state
    ss[_K + "base"] = df
    ss[_K + "base_years"] = tuple(c for c in df.columns if c.isdigit())
    ss[_K + "df"] = df
    ss[_K + "version"] = ss.get(_K + "version", 0) + 1


def _settings() -> None:
    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    c1.text_input("Company name", key=_K + "company", placeholder="e.g. Atlas Logistics SARL")
    c2.selectbox("Currency", config.CURRENCIES, key=_K + "currency")
    c3.selectbox("Reporting units", list(UNIT_OPTIONS), key=_K + "units",
                 help="The units used in your statements, e.g. 'in thousands'.")
    c4.number_input("Latest fiscal year", min_value=1990, max_value=2100, step=1,
                    key=_K + "latest_year",
                    help="The calendar year in which the fiscal year ENDS.")

    b1, b2, _ = st.columns([1, 1, 4])
    if b1.button("Add previous year", key=_K + "add_year"):
        st.session_state[_K + "n_years"] += 1
    if b2.button("Remove year", key=_K + "remove_year",
                 disabled=st.session_state[_K + "n_years"] <= 1,
                 help="Removes the oldest year and its values."):
        st.session_state[_K + "n_years"] -= 1


def _tables() -> pd.DataFrame:
    ss = st.session_state
    years = _years()
    wanted = tuple(str(y) for y in years)
    if ss[_K + "base_years"] != wanted:
        if len(ss[_K + "base_years"]) == len(wanted):
            # Latest fiscal year corrected: values keep their column, labels change.
            _set_base(relabel_years(ss[_K + "df"], years))
        else:
            # A year added or removed: values stay with their year.
            _set_base(resize_table(ss[_K + "df"], years))
    df = ss[_K + "base"]
    st.caption(BLANK_HINT)
    st.caption(SIGN_HINT)
    st.caption(DOT_HINT)

    parts = []
    tag = str(ss[_K + "version"])
    for title, group in SECTIONS:
        section_header(title)
        parts.append(confirm_table(df.loc[FIELD_GROUPS[group]], key=f"{_K}{group}_{tag}"))
    combined = pd.concat(parts).reindex(df.index)
    ss[_K + "df"] = combined
    return combined


def _show_issues(issues, blocked) -> None:
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    infos = [i for i in issues if i.level == "info"]
    if errors:
        st.error("**Errors (must be fixed before analysis):**\n\n" +
                 "\n".join(f"- {i.message}" for i in errors))
    if warnings:
        st.warning("**Warnings (analysis can still run):**\n\n" +
                   "\n".join(f"- {i.message}" for i in warnings))
    if infos:
        st.info("\n".join(f"- {i.message}" for i in infos))
    if not issues:
        st.success("No validation issues found.")
    for fy, ratios in blocked.items():
        if ratios:
            with st.expander(f"FY{fy}: {len(ratios)} ratio(s) cannot be computed"):
                for ratio, missing in ratios.items():
                    st.markdown(f"- **{ratio}**: missing {', '.join(missing)}")


def _save_and_load(financials) -> None:
    with st.expander("Save or load a working session (JSON file on your computer)"):
        st.caption("The file is downloaded to your computer. SolvIQ does not store it.")
        name = (st.session_state[_K + "company"].strip() or "company").replace(" ", "_")
        st.download_button("Download working session (JSON)",
                           data=financials_to_json(financials),
                           file_name=f"{name}_manual_session.json",
                           mime="application/json", key=_K + "download")
        uploaded = st.file_uploader("Load a saved session", type=["json"], key=_K + "upload")
        if uploaded is not None and st.session_state.get(_K + "loaded_id") != uploaded.file_id:
            st.session_state[_K + "loaded_id"] = uploaded.file_id
            try:
                loaded = financials_from_json(uploaded.getvalue().decode("utf-8"))
            except (ValidationError, UnicodeDecodeError, ValueError):
                st.warning("This file is not a valid SolvIQ working session, so it was not "
                           "loaded.")
                return
            if not loaded.periods:
                st.warning("This session file contains no financial periods.")
                return
            df, currency, units = financials_to_table(loaded)
            years = sorted((p.fiscal_year for p in loaded.periods), reverse=True)
            _set_base(df)
            st.session_state[_K + "pending"] = {
                _K + "company": loaded.company.name,
                _K + "currency": currency if currency in config.CURRENCIES
                else config.CURRENCIES[0],
                _K + "units": next(k for k, v in UNIT_OPTIONS.items() if v == units),
                _K + "latest_year": years[0],
                _K + "n_years": years[0] - years[-1] + 1,
            }
            st.rerun()


def render() -> None:
    _init()
    section_header("Manual Financial Entry",
                   "Enter the company's figures yourself. The same analysis engine is used "
                   "for SEC, PDF and manual data.")
    _settings()
    df = _tables()

    ss = st.session_state
    units = UNIT_OPTIONS[ss[_K + "units"]]
    company = ss[_K + "company"].strip()
    financials = table_to_financials(df, company or "Unnamed company", ss[_K + "currency"],
                                     units, SourceType.MANUAL, "Manual entry")

    bad = unreadable_cells(df)
    if bad:
        st.warning("These cells could not be read as numbers. Please correct them:\n\n" +
                   "\n".join(f"- {FIELD_LABELS[f]}, FY{y}: '{raw}'" for f, y, raw in bad))

    dots = dot_thousands_cells(df)
    if dots:
        st.warning("Please check these values. They are read with a decimal point "
                   "(1.234 = one point two three four). If you meant thousands, type "
                   "1234 instead:\n\n" +
                   "\n".join(f"- {FIELD_LABELS[f]}, FY{y}: '{raw}'" for f, y, raw in dots))

    c1, c2, c3 = st.columns(3)
    if c1.button("Validate data", key=_K + "validate", use_container_width=True):
        ss[_K + "show_validation"] = True
    if c2.button("Clear form", key=_K + "clear", use_container_width=True):
        _set_base(empty_table(_years()))
        ss[_K + "show_validation"] = False
        st.rerun()

    issues = validate_financials(financials)
    has_errors = any(i.level == "error" for i in issues)
    reasons = []
    if not company:
        reasons.append("enter a company name")
    if bad:
        reasons.append("correct the unreadable cells")
    if has_errors:
        reasons.append("fix the validation errors")
    if c3.button("Generate Credit Analysis", key=_K + "generate", type="primary",
                 use_container_width=True, disabled=bool(reasons)):
        state.set_financials(financials)
        state.go_to("Dashboard")
    if reasons:
        st.caption("To generate the analysis: " + "; ".join(reasons) + ".")

    if ss[_K + "show_validation"]:
        _show_issues(issues, blocked_ratios(financials))

    _save_and_load(financials)
