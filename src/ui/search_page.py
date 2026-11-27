"""Owned by Person 2: Search page (find a company on SEC EDGAR, confirm it, fetch its data).

Flow: type a name/ticker -> pick one result with "This is the company" (ALWAYS required, even
for a single match) -> the public data result is fetched and summarised -> "Analyze Company".
No match, no statements or an SEC outage each get their own clearly worded screen, and the PDF
and manual-entry alternatives are always offered.

App data goes only through src/state.py. Page-local widget state uses keys prefixed
"p2_search_". The modules are imported (not their functions) so tests can monkeypatch
``company_search.search_companies`` and ``public_data.fetch_public_financials``.
Only Streamlit APIs available in 1.35 are used.
"""
from __future__ import annotations

import logging
import re
from html import escape
from typing import Optional

import pandas as pd
import streamlit as st

from src import company_search, config, public_data, state
from src.models import (
    FIELD_LABELS,
    CompanyFinancials,
    CompanyMatch,
    DataAvailability,
    PublicDataResult,
)
from src.sec_client import SecClientError, SecConfigError, SecRateLimitError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------- texts and keys

SEARCH_LABEL = "Company name or ticker"
SEARCH_PLACEHOLDER = "Enter company name, e.g. Apple"
EXAMPLE_COMPANIES = ("Apple", "Microsoft", "Tesla", "Coca-Cola", "Amazon")
CONFIRM_LABEL = "This is the company"
ANALYZE_LABEL = "Analyze Company"
ANALYZE_ANYWAY_LABEL = "Analyze anyway"
SUPPLEMENT_LABEL = "Supplement the data manually"
CHANGE_LABEL = "Choose a different company"
RETRY_LABEL = "Retry"
OPTION_A_LABEL = "Option A — Upload Financial Statements (PDF)"
OPTION_B_LABEL = "Option B — Enter Financial Data Manually"
LINK_PDF_LABEL = "Upload PDF instead"
LINK_MANUAL_LABEL = "Enter data manually instead"
SOURCE_LINE = "Financial data source: SEC EDGAR"

SEARCH_OUTAGE_MESSAGE = ("Connection problem: the company search could not reach the SEC "
                         "(EDGAR) right now. This is NOT a \"company not found\" result and NOT "
                         "proof that financial statements do not exist. Please retry in a few "
                         "minutes, or continue with one of the options below.")
SEARCH_RATE_LIMIT_MESSAGE = ("Connection problem: the SEC is temporarily limiting requests from "
                             "this app. This is NOT a \"company not found\" result. Please wait a "
                             "few minutes and retry, or continue with one of the options below.")
SEARCH_UNEXPECTED_MESSAGE = ("The company search failed unexpectedly. This is NOT a \"company "
                             "not found\" result. Please retry, or continue with one of the "
                             "options below.")
CIK_MISMATCH_MESSAGE = ("The fetched data does not belong to the selected company, so it was "
                        "not used. Please retry.")

KEY_PREFIX = "p2_search_"
K_QUERY = KEY_PREFIX + "query"
K_LAST_QUERY = KEY_PREFIX + "last_query"      # page-local, non-widget
K_RESULT_CIK = KEY_PREFIX + "result_cik"      # CIK the stored PublicDataResult was fetched for
K_CHANGE = KEY_PREFIX + "change"
K_RETRY_SEARCH = KEY_PREFIX + "retry_search"
K_RETRY_FETCH = KEY_PREFIX + "retry_fetch"
K_ANALYZE = KEY_PREFIX + "analyze"
K_SUPPLEMENT = KEY_PREFIX + "supplement"
K_OPT_PDF = KEY_PREFIX + "opt_pdf"
K_OPT_MANUAL = KEY_PREFIX + "opt_manual"
K_LINK_PDF = KEY_PREFIX + "link_pdf"
K_LINK_MANUAL = KEY_PREFIX + "link_manual"

_PAGE_CSS = """
<style>
div[data-testid="stTextInput"] input { font-size: 1.2rem; padding: 0.75rem 0.9rem; }
</style>
"""


def chip_key(name: str) -> str:
    """Widget key of an example chip, e.g. "Coca-Cola" -> "p2_search_chip_coca_cola"."""
    return KEY_PREFIX + "chip_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def confirm_key(cik: str) -> str:
    return KEY_PREFIX + "confirm_" + cik


# ---------------------------------------------------------------------- data access

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_search(query: str) -> list[CompanyMatch]:
    """Search results by query string. Exceptions (outages) are never cached by Streamlit."""
    return company_search.search_companies(query)


def _clear_selection() -> None:
    state.set_selected_company(None)
    state.set_public_data_result(None)
    st.session_state.pop(K_RESULT_CIK, None)


def _set_query(name: str) -> None:
    """on_click of an example chip: runs before the text input is drawn."""
    st.session_state[K_QUERY] = name


def _confirm(match: CompanyMatch) -> None:
    """on_click of "This is the company": select it and drop any older result."""
    _clear_selection()
    state.set_selected_company(match)


def _retry_fetch() -> None:
    state.set_public_data_result(None)
    st.session_state.pop(K_RESULT_CIK, None)


def _sync_query() -> str:
    """Restore the query after page switches; a changed query clears the old selection."""
    if K_QUERY not in st.session_state and st.session_state.get(K_LAST_QUERY):
        st.session_state[K_QUERY] = st.session_state[K_LAST_QUERY]
    return st.session_state.get(K_QUERY, "") or ""


def _on_query_seen(query: str) -> None:
    if st.session_state.get(K_LAST_QUERY, "") != query:
        st.session_state[K_LAST_QUERY] = query
        _clear_selection()


def _get_result(selected: CompanyMatch) -> PublicDataResult:
    """Stored result for the selected CIK, or a fresh fetch (never cache_data'd)."""
    result = state.get_public_data_result()
    if result is not None and st.session_state.get(K_RESULT_CIK) == selected.cik:
        return result
    with st.spinner(f"Fetching SEC EDGAR data for {selected.name}..."):
        result = public_data.fetch_public_financials(selected)
    state.set_public_data_result(result)
    st.session_state[K_RESULT_CIK] = selected.cik
    return result


# ---------------------------------------------------------------------- small widgets

def _card(lines: list[str]) -> None:
    """Escaped HTML card; first line bold."""
    if not lines:
        return
    head = f"<div style='font-size:1.1rem;font-weight:700'>{escape(lines[0])}</div>"
    body = "".join(f"<div style='color:#475569'>{escape(line)}</div>" for line in lines[1:])
    st.markdown(f"<div class='cr-card'>{head}{body}</div>", unsafe_allow_html=True)


def _render_links() -> None:
    col_a, col_b, _ = st.columns([1, 1, 3])
    if col_a.button(LINK_PDF_LABEL, key=K_LINK_PDF):
        state.go_to("Upload PDF")
    if col_b.button(LINK_MANUAL_LABEL, key=K_LINK_MANUAL):
        state.go_to("Manual Entry")


def _render_options() -> None:
    """The two big alternative-path buttons."""
    col_a, col_b = st.columns(2)
    if col_a.button(OPTION_A_LABEL, key=K_OPT_PDF, use_container_width=True, type="primary"):
        state.go_to("Upload PDF")
    if col_b.button(OPTION_B_LABEL, key=K_OPT_MANUAL, use_container_width=True, type="primary"):
        state.go_to("Manual Entry")


def _render_no_data(detail: Optional[str] = None) -> None:
    """COMPANY_NOT_FOUND / NO_FINANCIAL_STATEMENTS screen with the exact config texts."""
    st.info(config.NO_DATA_MESSAGE)
    _render_options()
    st.caption(config.NO_DATA_FOOTNOTE)
    if detail:
        with st.expander("Details"):
            st.write(detail)


def _render_outage(message: str, retry_key: str, on_retry=None) -> None:
    """Outage / rate-limit / config screen. Never shows NO_DATA_MESSAGE."""
    st.warning(message)
    st.button(RETRY_LABEL, key=retry_key, on_click=on_retry)
    _render_options()


# ---------------------------------------------------------------------- search results

def _search_error_message(exc: SecClientError) -> str:
    if isinstance(exc, SecConfigError):
        return SecConfigError.default_message
    if isinstance(exc, SecRateLimitError):
        return SEARCH_RATE_LIMIT_MESSAGE
    return SEARCH_OUTAGE_MESSAGE


def _render_search(query: str) -> None:
    try:
        matches = _cached_search(query)
    except SecClientError as exc:
        _render_outage(_search_error_message(exc), K_RETRY_SEARCH)
        return
    except Exception:  # never crash, never pretend "not found"
        logger.exception("Unexpected error in company search")
        _render_outage(SEARCH_UNEXPECTED_MESSAGE, K_RETRY_SEARCH)
        return

    if not matches:
        _render_no_data()
        return

    st.caption(f"{len(matches)} matching compan{'y' if len(matches) == 1 else 'ies'} found. "
               "Please confirm the right one.")
    for m in matches:
        _card([m.name, f"Ticker: {m.ticker or 'n/a'}  ·  CIK: {m.cik}", SOURCE_LINE])
        st.button(CONFIRM_LABEL, key=confirm_key(m.cik), on_click=_confirm, args=(m,))


# ---------------------------------------------------------------------- selected company

def _period_table(f: CompanyFinancials) -> pd.DataFrame:
    return pd.DataFrame([{
        "Fiscal year": str(p.fiscal_year),
        "Period end": p.period_end.isoformat() if p.period_end else "n/a",
        "Form": p.form_type or "n/a",
        "Filed (latest 10-K reporting it)": p.filing_date.isoformat() if p.filing_date else "n/a",
        "Currency": p.currency,
    } for p in f.periods])


def _render_company_summary(selected: CompanyMatch, f: Optional[CompanyFinancials]) -> None:
    """Official identity card (from submissions when available)."""
    if f is None:
        _card([selected.name, f"Ticker: {selected.ticker or 'n/a'}  ·  CIK: {selected.cik}",
               SOURCE_LINE])
        return
    c = f.company
    sic = f"SIC {c.sic_code}" if c.sic_code else "SIC n/a"
    sector = f" — {c.sector}" if c.sector else ""
    _card([c.name, f"Ticker: {c.ticker or 'n/a'}  ·  CIK: {c.cik}", f"{sic}{sector}",
           SOURCE_LINE + (f"  ·  {c.reporting_framework}" if c.reporting_framework else "")])
    if c.is_financial_institution:
        st.warning(config.FINANCIAL_INSTITUTION_MESSAGE)


def _render_warnings(f: CompanyFinancials) -> None:
    other = [w for w in f.warnings if w != config.FINANCIAL_INSTITUTION_MESSAGE]
    if other:
        with st.expander(f"Data notes from the SEC import ({len(other)})"):
            for w in other:
                st.write(f"- {w}")


def _analyze(selected: CompanyMatch, result: PublicDataResult) -> None:
    """Store the confirmed financials and go to the Dashboard (with a CIK safety check)."""
    f = result.financials
    if f is None or not f.periods or f.company.cik != selected.cik:
        st.error(CIK_MISMATCH_MESSAGE)
        st.button(RETRY_LABEL, key=K_RETRY_FETCH, on_click=_retry_fetch)
        return
    state.set_financials(f)
    state.go_to("Dashboard")


def _render_found(selected: CompanyMatch, result: PublicDataResult) -> None:
    """AVAILABLE and INSUFFICIENT_DATA: periods, gaps, analyze."""
    f = result.financials
    # The FI message already has its own warning box above; don't show it twice.
    message = result.message.replace(config.FINANCIAL_INSTITUTION_MESSAGE, "").strip()
    if result.status == DataAvailability.AVAILABLE:
        st.success(message)
    else:
        st.warning(message)
    st.markdown("**Available annual periods**")
    st.table(_period_table(f))
    _render_warnings(f)

    insufficient = result.status == DataAvailability.INSUFFICIENT_DATA
    if insufficient:
        latest = f.latest()
        core = public_data.missing_core_fields(f)
        st.markdown("**Missing core items (latest period):** "
                    + ", ".join(FIELD_LABELS[x] for x in core))
        others = [x for x in latest.missing_fields() if x not in core] if latest else []
        if others:
            st.caption("Other missing items: " + ", ".join(FIELD_LABELS[x] for x in others))

    col_a, col_b = st.columns(2)
    label = ANALYZE_ANYWAY_LABEL if insufficient else ANALYZE_LABEL
    if col_a.button(label, key=K_ANALYZE, type="primary", use_container_width=True):
        _analyze(selected, result)
    if insufficient and col_b.button(SUPPLEMENT_LABEL, key=K_SUPPLEMENT,
                                     use_container_width=True):
        state.go_to("Manual Entry")


def _render_selected(selected: CompanyMatch) -> None:
    st.button(CHANGE_LABEL, key=K_CHANGE, on_click=_clear_selection)
    result = _get_result(selected)
    _render_company_summary(selected, result.financials)

    status = result.status
    if status in (DataAvailability.AVAILABLE, DataAvailability.INSUFFICIENT_DATA) \
            and result.financials is not None and result.financials.periods:
        _render_found(selected, result)
    elif status in (DataAvailability.NO_FINANCIAL_STATEMENTS,
                    DataAvailability.COMPANY_NOT_FOUND):
        if result.financials is not None:
            _render_warnings(result.financials)
        _render_no_data(detail=result.message)
    else:  # API_UNAVAILABLE, RATE_LIMITED (and anything unexpected): an outage, not "no data"
        _render_outage(result.message, K_RETRY_FETCH, on_retry=_retry_fetch)


# ---------------------------------------------------------------------- page

def render() -> None:
    """Search page entry point."""
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    st.title(config.HOME_HEADING)
    st.write(config.HOME_SUBTITLE)

    _sync_query()
    query = st.text_input(SEARCH_LABEL, key=K_QUERY, placeholder=SEARCH_PLACEHOLDER).strip()
    cols = st.columns(len(EXAMPLE_COMPANIES))
    for col, name in zip(cols, EXAMPLE_COMPANIES):
        col.button(name, key=chip_key(name), on_click=_set_query, args=(name,))
    _render_links()
    _on_query_seen(query)

    selected = state.get_selected_company()
    if selected is not None:
        _render_selected(selected)
    elif query:
        _render_search(query)
