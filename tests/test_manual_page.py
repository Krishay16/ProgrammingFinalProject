"""Headless tests of the Manual Entry page (Person 3) with Streamlit's AppTest.

AppTest cannot type into st.data_editor cells, so these tests put a filled table into the
page's own session key and then use the real buttons. The parsing itself is covered in
tests/test_manual_input.py.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.manual_input import empty_table
from src.models import SourceType

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
K = "_p3_manual_"


def _manual_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Manual Entry").run()
    return at


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _fill(at, values: dict, years=(2024,)):
    df = empty_table(list(years))
    for (field, year), v in values.items():
        df.at[field, year] = v
    at.session_state[K + "base"] = df
    at.session_state[K + "df"] = df
    at.session_state[K + "base_years"] = tuple(str(y) for y in sorted(years, reverse=True))
    at.session_state[K + "version"] = at.session_state[K + "version"] + 1
    at.session_state[K + "latest_year"] = max(years)
    at.session_state[K + "n_years"] = len(years)


BS_AND_IS = {("current_assets", "2024"): "200", ("current_liabilities", "2024"): "100",
             ("total_assets", "2024"): "1,000", ("total_liabilities", "2024"): "600",
             ("total_equity", "2024"): "400", ("revenue", "2024"): "1,500",
             ("ebit", "2024"): "150", ("net_income", "2024"): "(20)"}


def test_page_renders_three_sections_and_hint():
    at = _manual_page()
    assert not at.exception and not at.error
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    for title in ("A. Balance Sheet", "B. Income Statement", "C. Cash Flow Statement"):
        assert title in text
    assert "Blank is treated as missing, not zero." in text
    assert _button(at, "Generate Credit Analysis").disabled   # empty form


def test_add_and_remove_year():
    at = _manual_page()
    _button(at, "Add previous year").click().run()
    assert at.session_state[K + "n_years"] == 2
    _button(at, "Remove year").click().run()
    assert at.session_state[K + "n_years"] == 1
    assert not at.exception


def test_generate_sends_confirmed_figures_to_dashboard():
    at = _manual_page()
    _fill(at, BS_AND_IS)
    at.text_input(key=K + "company").set_value("Atlas Test SARL").run()
    at.selectbox(key=K + "currency").set_value("EUR").run()
    at.selectbox(key=K + "units").set_value("Thousands").run()
    gen = _button(at, "Generate Credit Analysis")
    assert not gen.disabled
    gen.click().run()
    assert not at.exception
    f = at.session_state["_solviq_financials"]
    assert f.company.name == "Atlas Test SARL" and f.source_type == SourceType.MANUAL
    p = f.latest()
    assert p.currency == "EUR"
    assert p.get("revenue") == 1_500_000.0          # 1,500 thousand
    assert p.get("net_income") == -20_000.0
    assert p.get("operating_cash_flow") is None     # cash flow left blank -> missing
    assert at.session_state["_solviq_page"] == "Dashboard"


def test_validate_shows_grouped_issues_and_blocked_ratios():
    at = _manual_page()
    _fill(at, {**BS_AND_IS, ("total_equity", "2024"): "-50"})
    at.text_input(key=K + "company").set_value("Neg Equity Co").run()
    _button(at, "Validate data").click().run()
    assert not at.exception
    assert any("Negative equity" in w.value for w in at.warning)
    assert any("cannot be computed" in e.label for e in at.expander)
    assert not _button(at, "Generate Credit Analysis").disabled   # warnings are OK


def test_text_in_number_cell_is_listed_and_blocks_generate():
    at = _manual_page()
    _fill(at, {**BS_AND_IS, ("revenue", "2024"): "about 1500"})
    at.text_input(key=K + "company").set_value("Typo Co").run()
    assert not at.exception
    assert any("about 1500" in w.value for w in at.warning)
    assert _button(at, "Generate Credit Analysis").disabled


def test_clear_form_empties_values():
    at = _manual_page()
    _fill(at, BS_AND_IS)
    at.run()
    _button(at, "Clear form").click().run()
    df = at.session_state[K + "df"]
    assert df[["2024"]].isna().all().all()
