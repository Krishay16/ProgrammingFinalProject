"""Owned by Person 3: shared editable confirmation table widget.

Used by the Manual Entry page and the Upload PDF page. The analyst sees every value,
can correct it, and flagged values (e.g. ambiguous PDF extractions) are listed above the
table and explained in a read-only "Notes" column.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from src.manual_input import LINE_ITEM_COL, _display_number, year_columns
from src.models import FIELD_LABELS

NOTES_COL = "Notes"


def _as_text(value) -> Optional[str]:
    """Show numbers as plain text so the analyst can also type '(1,234)' or '1.234,5'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _display_number(float(value))
    return str(value)


def build_notes(df: pd.DataFrame, flags: Optional[dict[tuple[str, str], str]]) -> pd.Series:
    """One note string per row, combining all flags for that field across years."""
    notes = pd.Series([""] * len(df), index=df.index, dtype="object")
    for (field, year), message in (flags or {}).items():
        if field in notes.index:
            prefix = f"{year}: {message}"
            notes[field] = f"{notes[field]}; {prefix}" if notes[field] else prefix
    return notes


def confirm_table(df: pd.DataFrame, key: str,
                  flags: Optional[dict[tuple[str, str], str]] = None) -> pd.DataFrame:
    """Show an editable table; return the edited DataFrame (same columns as `df`).

    `flags` maps (field, year) -> message, e.g. ("revenue", "2024") ->
    "Ambiguous: two candidates found on page 4". Year columns are editable text;
    "Line item" and "Notes" are read-only.
    """
    years = year_columns(df)
    shown = df.copy()
    for c in years:
        shown[c] = shown[c].map(_as_text).astype("object")
    if LINE_ITEM_COL not in shown.columns:
        shown.insert(0, LINE_ITEM_COL, [FIELD_LABELS.get(i, i) for i in shown.index])
    shown[NOTES_COL] = build_notes(shown, flags)

    if flags:
        lines = [f"- **{FIELD_LABELS.get(field, field)}**, {year}: {msg}"
                 for (field, year), msg in flags.items()]
        st.warning("Please review these flagged values before confirming:\n\n" +
                   "\n".join(lines))

    column_config = {
        LINE_ITEM_COL: st.column_config.TextColumn(LINE_ITEM_COL, disabled=True, width="large"),
        NOTES_COL: st.column_config.TextColumn(NOTES_COL, disabled=True, width="medium"),
    }
    for c in years:
        column_config[c] = st.column_config.TextColumn(
            f"FY{c}", help="Type a number. Blank = missing. (1,234) = negative.")

    edited = st.data_editor(
        shown,
        key=key,
        hide_index=True,
        num_rows="fixed",
        use_container_width=True,
        column_order=[LINE_ITEM_COL, *years, NOTES_COL],
        column_config=column_config,
    )
    edited = edited.drop(columns=[NOTES_COL])
    edited.index = df.index  # keep field keys even though the index is hidden
    return edited[[c for c in df.columns if c in edited.columns]]
