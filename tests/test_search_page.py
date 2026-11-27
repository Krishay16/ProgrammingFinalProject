"""Headless tests of the Search page (Person 2) with Streamlit's AppTest. No network.

``company_search.search_companies`` and ``public_data.fetch_public_financials`` are
monkeypatched (the page calls them through their modules). All company data here is
SYNTHETIC (invented names, CIKs and values), except that the names Apple/Microsoft are used
as search text.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import company_search, config, public_data
from src.models import (
    CompanyFinancials,
    CompanyInfo,
    CompanyMatch,
    DataAvailability,
    FinancialPeriod,
    FinancialValue,
    PublicDataResult,
    SourceType,
)
from src.sec_client import SecConfigError, SecRateLimitError, SecUnavailableError
from src.ui import search_page as sp

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

M1 = CompanyMatch(name="SYNTHETIC ALPHA INC", ticker="SYNA", cik="0000000001", match_score=1.0)
M2 = CompanyMatch(name="SYNTHETIC BETA CORP", ticker="SYNB", cik="0000000002", match_score=0.7)


def _financials(cik: str, name: str = "SYNTHETIC ALPHA INC (official)", fi: bool = False,
                revenue: float | None = 100.0) -> CompanyFinancials:
    period = FinancialPeriod(
        fiscal_year=2024, period_end=date(2024, 12, 31), filing_date=date(2025, 2, 1),
        form_type="10-K", revenue=FinancialValue(value=revenue),
        total_assets=FinancialValue(value=500.0), current_liabilities=FinancialValue(value=50.0))
    warnings = [config.FINANCIAL_INSTITUTION_MESSAGE] if fi else []
    return CompanyFinancials(
        company=CompanyInfo(name=name, ticker="SYNA", cik=cik, sic_code="6022" if fi else "3571",
                            sector="SYNTHETIC sector", is_financial_institution=fi),
        source_type=SourceType.SEC_EDGAR, periods=[period], warnings=warnings)


class Recorder:
    """Records calls and returns/raises a configurable outcome."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list = []

    def __call__(self, arg, *args, **kwargs):
        self.calls.append(arg)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome(arg) if callable(self.outcome) else self.outcome


@pytest.fixture(autouse=True)
def _clear_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def _patch(monkeypatch, search, fetch=None) -> tuple[Recorder, Recorder]:
    s = Recorder(search)
    f = Recorder(fetch if fetch is not None else PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik), message="SYNTHETIC ok"))
    monkeypatch.setattr(company_search, "search_companies", s)
    monkeypatch.setattr(public_data, "fetch_public_financials", f)
    return s, f


def _app() -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    return at


def _search(at: AppTest, query: str) -> AppTest:
    at.text_input(key=sp.K_QUERY).set_value(query).run()
    assert not at.exception
    return at


def _all_text(at: AppTest) -> str:
    parts = []
    for group in (at.info, at.warning, at.error, at.success, at.caption, at.markdown):
        parts += [str(e.value) for e in group]
    return "\n".join(parts)


def _labels(at: AppTest) -> list[str]:
    return [b.label for b in at.button]


# --------------------------------------------------------------------------- initial page

def test_initial_page_has_heading_chips_and_links(monkeypatch):
    s, _ = _patch(monkeypatch, [])
    at = _app()
    assert not at.exception
    assert at.title[0].value == config.HOME_HEADING
    assert config.HOME_SUBTITLE in _all_text(at)
    assert at.text_input(key=sp.K_QUERY).placeholder == sp.SEARCH_PLACEHOLDER
    labels = _labels(at)
    for name in sp.EXAMPLE_COMPANIES:
        assert name in labels
    assert sp.LINK_PDF_LABEL in labels and sp.LINK_MANUAL_LABEL in labels
    assert s.calls == []  # nothing searched before the analyst types


def test_example_chip_fills_query_and_searches(monkeypatch):
    s, _ = _patch(monkeypatch, [M1])
    at = _app()
    at.button(key=sp.chip_key("Coca-Cola")).click().run()
    assert not at.exception
    assert at.text_input(key=sp.K_QUERY).value == "Coca-Cola"
    assert s.calls == ["Coca-Cola"]


# --------------------------------------------------------------------------- search outcomes

def test_no_match_shows_exact_no_data_message_and_both_options(monkeypatch):
    _patch(monkeypatch, [])
    at = _search(_app(), "Zzyzx SYNTHETIC Nonexistent")
    assert any(e.value == config.NO_DATA_MESSAGE for e in at.info)
    assert any(e.value == config.NO_DATA_FOOTNOTE for e in at.caption)
    labels = _labels(at)
    assert sp.OPTION_A_LABEL in labels and sp.OPTION_B_LABEL in labels


@pytest.mark.parametrize("error", [SecUnavailableError(), SecRateLimitError(),
                                   SecConfigError(), RuntimeError("bug")])
def test_outage_during_search_is_not_shown_as_no_data(monkeypatch, error):
    _patch(monkeypatch, error)
    at = _search(_app(), "Apple")
    text = _all_text(at)
    assert config.NO_DATA_MESSAGE not in text
    assert at.warning, "an outage warning must be shown"
    labels = _labels(at)
    assert sp.RETRY_LABEL in labels
    assert sp.OPTION_A_LABEL in labels and sp.OPTION_B_LABEL in labels
    if isinstance(error, SecConfigError):
        assert "SEC_CONTACT_EMAIL" in text


def test_outage_is_not_cached_retry_searches_again(monkeypatch):
    s, _ = _patch(monkeypatch, SecUnavailableError())
    at = _search(_app(), "Apple")
    s.outcome = [M1]
    at.button(key=sp.K_RETRY_SEARCH).click().run()
    assert not at.exception
    assert len(s.calls) == 2
    assert sp.CONFIRM_LABEL in _labels(at)


def test_results_show_cards_and_require_confirmation(monkeypatch):
    _, f = _patch(monkeypatch, [M1, M2])
    at = _search(_app(), "SYNTHETIC")
    text = _all_text(at)
    assert M1.name in text and M2.name in text and M1.cik in text
    assert sp.SOURCE_LINE in text
    assert _labels(at).count(sp.CONFIRM_LABEL) == 2
    assert f.calls == []
    assert at.session_state["_solviq_selected_company"] is None


def test_single_match_still_needs_confirmation(monkeypatch):
    _, f = _patch(monkeypatch, [M1])
    at = _search(_app(), "SYNTHETIC ALPHA")
    assert f.calls == []
    assert at.session_state["_solviq_selected_company"] is None
    at.button(key=sp.confirm_key(M1.cik)).click().run()
    assert not at.exception
    assert [m.cik for m in f.calls] == [M1.cik]
    assert at.session_state["_solviq_selected_company"].cik == M1.cik


# --------------------------------------------------------------------------- after confirmation

def _confirmed(monkeypatch, fetch, match=M1) -> tuple[AppTest, Recorder]:
    _, f = _patch(monkeypatch, [match], fetch)
    at = _search(_app(), "SYNTHETIC")
    at.button(key=sp.confirm_key(match.cik)).click().run()
    assert not at.exception
    return at, f


def test_available_summary_and_analyze_goes_to_dashboard(monkeypatch):
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik), message="SYNTHETIC ok"))
    text = _all_text(at)
    assert "SYNTHETIC ALPHA INC (official)" in text  # official name, not the search title
    assert "SIC 3571" in text
    table = at.table[0].value
    assert list(table["Fiscal year"]) == ["2024"]
    assert list(table["Period end"]) == ["2024-12-31"]
    assert list(table["Form"]) == ["10-K"] and list(table["Filed (latest 10-K reporting it)"]) == ["2025-02-01"]
    at.button(key=sp.K_ANALYZE).click().run()
    assert not at.exception
    assert at.session_state["_solviq_page"] == "Dashboard"
    assert at.session_state["_solviq_financials"].company.cik == M1.cik


def test_analyze_refuses_data_for_another_cik(monkeypatch):
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials("0000000999"), message="x"))
    at.button(key=sp.K_ANALYZE).click().run()
    assert not at.exception
    assert at.session_state["_solviq_page"] == "Search"
    assert at.session_state["_solviq_financials"] is None
    assert any(sp.CIK_MISMATCH_MESSAGE in e.value for e in at.error)


def test_financial_institution_message_shown(monkeypatch):
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik, fi=True), message="x"))
    shown = [e.value for e in [*at.warning, *at.success]]
    assert shown.count(config.FINANCIAL_INSTITUTION_MESSAGE) == 1
    assert sum(config.FINANCIAL_INSTITUTION_MESSAGE in v for v in shown) == 1  # not twice


def test_financial_institution_message_not_duplicated_in_status(monkeypatch):
    msg = "SYNTHETIC found. " + config.FINANCIAL_INSTITUTION_MESSAGE
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik, fi=True), message=msg))
    shown = [e.value for e in [*at.warning, *at.success]]
    assert sum(config.FINANCIAL_INSTITUTION_MESSAGE in v for v in shown) == 1


def test_insufficient_data_lists_missing_and_offers_both_paths(monkeypatch):
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.INSUFFICIENT_DATA,
        financials=_financials(M1.cik, revenue=None), message="SYNTHETIC insufficient"))
    text = _all_text(at)
    assert "Missing core items" in text and "Revenue" in text
    labels = _labels(at)
    assert sp.ANALYZE_ANYWAY_LABEL in labels and sp.SUPPLEMENT_LABEL in labels
    at.button(key=sp.K_ANALYZE).click().run()
    assert at.session_state["_solviq_page"] == "Dashboard"


def test_no_financial_statements_shows_no_data_message(monkeypatch):
    f = _financials(M1.cik).model_copy(update={"periods": [], "warnings": ["SYNTHETIC IFRS"]})
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.NO_FINANCIAL_STATEMENTS, financials=f, message="none"))
    assert any(e.value == config.NO_DATA_MESSAGE for e in at.info)
    assert any(e.value == config.NO_DATA_FOOTNOTE for e in at.caption)
    labels = _labels(at)
    assert sp.OPTION_A_LABEL in labels and sp.OPTION_B_LABEL in labels
    assert sp.ANALYZE_LABEL not in labels


@pytest.mark.parametrize("status", [DataAvailability.API_UNAVAILABLE,
                                    DataAvailability.RATE_LIMITED])
def test_fetch_outage_shows_retry_not_no_data(monkeypatch, status):
    at, f = _confirmed(monkeypatch, PublicDataResult(status=status, message="SYNTHETIC outage"))
    assert config.NO_DATA_MESSAGE not in _all_text(at)
    assert any("SYNTHETIC outage" in e.value for e in at.warning)
    labels = _labels(at)
    assert sp.RETRY_LABEL in labels and sp.OPTION_A_LABEL in labels
    f.outcome = PublicDataResult(status=DataAvailability.AVAILABLE,
                                 financials=_financials(M1.cik), message="SYNTHETIC ok")
    at.button(key=sp.K_RETRY_FETCH).click().run()
    assert len(f.calls) == 2
    assert sp.ANALYZE_LABEL in _labels(at)


def test_result_is_not_refetched_on_every_rerun(monkeypatch):
    at, f = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik), message="ok"))
    at.run()
    at.run()
    assert len(f.calls) == 1


def test_new_search_clears_old_selection_and_result(monkeypatch):
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik), message="ok"))
    assert at.session_state["_solviq_public_result"] is not None
    _search(at, "Microsoft")
    assert at.session_state["_solviq_selected_company"] is None
    assert at.session_state["_solviq_public_result"] is None
    assert sp.ANALYZE_LABEL not in _labels(at)


def test_change_company_button_clears_selection(monkeypatch):
    at, _ = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik), message="ok"))
    at.button(key=sp.K_CHANGE).click().run()
    assert at.session_state["_solviq_selected_company"] is None
    assert at.session_state["_solviq_public_result"] is None
    assert sp.CONFIRM_LABEL in _labels(at)


@pytest.mark.parametrize("key, page", [(sp.K_LINK_PDF, "Upload PDF"),
                                       (sp.K_LINK_MANUAL, "Manual Entry")])
def test_small_links_navigate(monkeypatch, key, page):
    _patch(monkeypatch, [])
    at = _app()
    at.button(key=key).click().run()
    assert at.session_state["_solviq_page"] == page


@pytest.mark.parametrize("key, page", [(sp.K_OPT_PDF, "Upload PDF"),
                                       (sp.K_OPT_MANUAL, "Manual Entry")])
def test_option_buttons_navigate(monkeypatch, key, page):
    _patch(monkeypatch, [])
    at = _search(_app(), "Zzyzx")
    at.button(key=key).click().run()
    assert at.session_state["_solviq_page"] == page


def test_selection_survives_page_switch(monkeypatch):
    at, f = _confirmed(monkeypatch, PublicDataResult(
        status=DataAvailability.AVAILABLE, financials=_financials(M1.cik), message="ok"))
    at.sidebar.radio[0].set_value("Methodology").run()
    at.sidebar.radio[0].set_value("Search").run()
    assert not at.exception
    assert at.text_input(key=sp.K_QUERY).value == "SYNTHETIC"
    assert at.session_state["_solviq_selected_company"].cik == M1.cik
    assert len(f.calls) == 1
