"""Headless smoke tests of app.py using Streamlit's AppTest (no browser needed)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import config

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _app() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    return at


def _texts(elements) -> str:
    return " ".join(e.value for e in elements)


def test_app_starts_without_exception():
    at = _app()
    assert not at.exception
    assert "No company loaded" in _texts(at.sidebar.caption)


def test_footer_shows_score_disclaimer():
    at = _app()
    assert any(config.SCORE_DISCLAIMER in m.value for m in at.markdown)


@pytest.mark.parametrize("page", config.PAGES)
def test_every_page_renders_placeholder_without_crashing(page):
    at = _app()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception
    assert not at.error, [e.value for e in at.error]


def test_demo_button_loads_synthetic_company():
    at = _app()
    next(b for b in at.sidebar.button if "SYNTHETIC" in b.label).click().run()
    assert not at.exception
    text = _texts(at.sidebar.caption)
    assert "SYNTHETIC" in text and "FY2024" in text


def test_reset_clears_company():
    at = _app()
    next(b for b in at.sidebar.button if "SYNTHETIC" in b.label).click().run()
    next(b for b in at.sidebar.button if b.label == "Reset").click().run()
    assert "No company loaded" in _texts(at.sidebar.caption)
