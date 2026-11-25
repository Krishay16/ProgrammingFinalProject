"""Owned by Person 3: Upload PDF page.

The analyst uploads PDF statements; figures are extracted locally in memory
(src.pdf_extractor), shown in the editable confirmation table with flags and evidence,
and only used after the analyst explicitly confirms them.

Privacy: the uploaded bytes and the extraction result live only in this browser
session's memory. Nothing is written to disk, logged, or sent to any external service.
Page-local state uses keys starting with "_p3_upload_".
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import config, state
from src.data_validation import validate_financials
from src.manual_input import (blocked_ratios, is_blank, table_to_financials,
                              unreadable_cells)
from src.models import FIELD_LABELS, SourceType
from src.pdf_extractor import PdfExtractionResult, extract_financials, result_to_table
from src.ui.confirm_table import confirm_table
from src.ui.manual_page import UNIT_OPTIONS, _show_issues
from src.ui.theme import section_header

_K = "_p3_upload_"
PRIVACY_NOTE = ("Files are processed locally in memory for this session only. They are not "
                "stored and are not sent to any external AI service.")
REVIEW_LABEL = "I have reviewed the extracted values and corrected any errors."
FLAGGED_LABEL = "I confirm the flagged values above."


def _extract(files) -> tuple[str, PdfExtractionResult]:
    """Run extraction once per set of uploaded files (cached in session memory)."""
    file_key = "|".join(f"{f.name}:{f.size}:{f.file_id}" for f in files)
    if st.session_state.get(_K + "file_key") != file_key:
        with st.spinner("Reading your PDF files..."):
            result = extract_financials([(f.name, f.getvalue()) for f in files])
        st.session_state[_K + "file_key"] = file_key
        st.session_state[_K + "result"] = result
        st.session_state[_K + "version"] = st.session_state.get(_K + "version", 0) + 1
    return file_key, st.session_state[_K + "result"]


def _file_status(files, result: PdfExtractionResult) -> None:
    failed = {entry.split(": ", 1)[0]: entry.split(": ", 1)[1] for entry in result.failed_files}
    for f in files:
        if f.name in failed:
            st.error(f"**{f.name}**: could not be read ({failed[f.name]}).")
        elif f.name in result.scanned_files:
            st.warning(f"**{f.name}**: this PDF looks scanned (image only). Text could not "
                       "be read reliably. Please enter the figures manually.")
        else:
            n = sum(1 for it in result.items if it.source_file == f.name)
            st.success(f"**{f.name}**: OK, {n} value(s) found.")
    if result.scanned_files or result.failed_files:
        if st.button("Enter the figures manually", key=_K + "manual_from_status"):
            state.go_to("Manual Entry")


def _evidence(result: PdfExtractionResult) -> None:
    with st.expander("Evidence for each extracted value (file, page, text as printed)"):
        if not result.items:
            st.caption("No values were extracted.")
            return
        rows = [{"Line item": FIELD_LABELS[it.field], "Year": it.fiscal_year,
                 "As printed": it.original_text, "File": it.source_file, "Page": it.page,
                 "Label found": it.matched_label, "Status": it.status, "Note": it.note}
                for it in sorted(result.items, key=lambda i: (i.source_file, i.page))]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def flagged_unedited(original: pd.DataFrame, edited: pd.DataFrame,
                     flags: dict[tuple[str, str], str]) -> list[tuple[str, str]]:
    """Flagged cells the analyst has not changed (same value, or still blank)."""
    out = []
    for field, year in flags:
        before, after = original.at[field, year], edited.at[field, year]
        if (is_blank(before) and is_blank(after)) or str(before) == str(after):
            out.append((field, year))
    return out


def _settings(result: PdfExtractionResult) -> tuple[str, str | None, str | None]:
    c1, c2, c3 = st.columns([3, 1, 1])
    selected = state.get_selected_company()
    company = c1.text_input("Company name", value=selected.name if selected else "",
                            key=_K + "company")
    ccy_index = config.CURRENCIES.index(result.currency) \
        if result.currency in config.CURRENCIES else None
    currency = c2.selectbox("Currency", config.CURRENCIES, index=ccy_index,
                            placeholder="Select (not detected)", key=_K + "currency_" +
                            str(st.session_state[_K + "version"]))
    unit_names = list(UNIT_OPTIONS)
    unit_index = next((i for i, n in enumerate(unit_names)
                       if UNIT_OPTIONS[n] == result.units), None)
    units = c3.selectbox("Reporting units", unit_names, index=unit_index,
                         placeholder="Select (not detected)",
                         help="Check against the statement header, e.g. 'in millions'.",
                         key=_K + "units_" + str(st.session_state[_K + "version"]))
    detected = []
    detected.append(f"currency {result.currency}" if result.currency
                    else "currency NOT detected")
    detected.append(f"units {result.units.name.lower()}" if result.units
                    else "units NOT detected")
    years = ", ".join(f"FY{y}" for y in result.fiscal_years) or "none"
    st.caption(f"Detected: {', '.join(detected)}; fiscal years {years}.")
    return company.strip(), currency, units


def render() -> None:
    section_header("Upload Financial Statements",
                   f"Upload your company's annual report or financial statements in PDF "
                   f"format. {config.APP_NAME} will extract the financial information for "
                   "your review.")
    st.caption(PRIVACY_NOTE)
    files = st.file_uploader("Upload PDF Files", type=["pdf"], accept_multiple_files=True,
                             key=_K + "files")
    if st.button("Enter data manually instead", key=_K + "manual"):
        state.go_to("Manual Entry")
    if not files:
        st.info("Upload one or more PDF files to begin. Scanned (image-only) PDFs cannot be "
                "read in this version.")
        return

    _, result = _extract(files)
    _file_status(files, result)
    for w in result.warnings:
        if "looks scanned" not in w:
            st.warning(w)
    if not result.items:
        st.info("No figures could be extracted. You can enter them manually instead.")
        return

    company, currency, unit_name = _settings(result)
    original, flags = result_to_table(result)
    section_header("Review the extracted values",
                   "Values are shown as printed in the statement (in the reporting units "
                   "above). Correct anything that is wrong. Blank means missing.")
    edited = confirm_table(original, key=f"{_K}table_{st.session_state[_K + 'version']}",
                           flags=flags)
    _evidence(result)

    bad = unreadable_cells(edited)
    if bad:
        st.warning("These cells could not be read as numbers. Please correct them:\n\n" +
                   "\n".join(f"- {FIELD_LABELS[f]}, FY{y}: '{raw}'" for f, y, raw in bad))

    reviewed = st.checkbox(REVIEW_LABEL, key=_K + "reviewed")
    pending = flagged_unedited(original, edited, flags)
    flagged_ok = True
    if pending:
        st.warning("These flagged values have not been changed. Check them against the "
                   "document before continuing:\n\n" +
                   "\n".join(f"- {FIELD_LABELS[f]}, FY{y}: {flags[(f, y)]}"
                             for f, y in pending))
        flagged_ok = st.checkbox(FLAGGED_LABEL, key=_K + "flagged_ok")

    reasons = []
    if not company:
        reasons.append("enter the company name")
    if currency is None or unit_name is None:
        reasons.append("select the currency and reporting units")
    if bad:
        reasons.append("correct the unreadable cells")
    if not (reviewed and flagged_ok):
        reasons.append("confirm that you reviewed the values")

    financials = None
    if currency is not None and unit_name is not None:
        names = ", ".join(f.name for f in files if f.name not in result.scanned_files)
        financials = table_to_financials(edited, company or "Unnamed company", currency,
                                         UNIT_OPTIONS[unit_name], SourceType.PDF, names)
        issues = validate_financials(financials)
        if any(i.level == "error" for i in issues):
            reasons.append("fix the validation errors")
        with st.expander("Validation results", expanded=any(i.level != "info"
                                                            for i in issues)):
            _show_issues(issues, blocked_ratios(financials))

    if st.button("Generate Credit Analysis", type="primary", key=_K + "generate",
                 disabled=bool(reasons)):
        state.set_financials(financials)
        state.go_to("Dashboard")
    if reasons:
        st.caption("To generate the analysis: " + "; ".join(reasons) + ".")
