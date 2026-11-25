"""Tests for the Upload PDF page (Person 3).

AppTest cannot upload files, so the full upload flow was checked in a browser; here we
test the page's empty state and its helper that decides which flags still need review.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.manual_input import empty_table
from src.ui.upload_page import PRIVACY_NOTE, flagged_unedited

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_upload_page_renders_with_privacy_note_and_manual_option():
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Upload PDF").run()
    assert not at.exception and not at.error
    assert any(PRIVACY_NOTE in c.value for c in at.caption)
    manual = next(b for b in at.button if b.label == "Enter data manually instead")
    manual.click().run()
    assert at.session_state["_solviq_page"] == "Manual Entry"


def test_flagged_unedited_lists_only_cells_the_analyst_did_not_change():
    original = empty_table([2024])
    original.at["revenue", "2024"] = "1500"        # flagged, has a value
    original.at["ebit", "2024"] = "200"            # flagged, will be corrected
    # cash flagged and blank (conflicting candidates), will be filled in
    edited = original.copy()
    edited.at["ebit", "2024"] = "210"
    flags = {("revenue", "2024"): "Ambiguous", ("ebit", "2024"): "Ambiguous",
             ("cash", "2024"): "Ambiguous", ("capex", "2024"): "Ambiguous"}
    edited.at["cash", "2024"] = "50"
    assert flagged_unedited(original, edited, flags) == [("revenue", "2024"),
                                                         ("capex", "2024")]
