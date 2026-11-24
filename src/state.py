"""Session-state helpers. Owned by Person 1.

Only use these helpers elsewhere, never raw st.session_state keys.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from src import config
from src.models import (AnalysisResult, CompanyFinancials, CompanyMatch,
                        PublicDataResult)

_PAGE = "_credara_page"
_COMPANY = "_credara_selected_company"
_PUBLIC = "_credara_public_result"
_FINANCIALS = "_credara_financials"
_ANALYSIS = "_credara_analysis"
_CONSENT = "_credara_llm_consent"

_DEFAULTS = {
    _PAGE: config.PAGES[0],
    _COMPANY: None,
    _PUBLIC: None,
    _FINANCIALS: None,
    _ANALYSIS: None,
    _CONSENT: False,
}


def init_state() -> None:
    """Create any missing keys. Safe to call on every rerun."""
    for key, default in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


def go_to(page: str) -> None:
    """Navigate to a page (must be in config.PAGES) and rerun the app."""
    if page not in config.PAGES:
        raise ValueError(f"Unknown page {page!r}; expected one of {config.PAGES}")
    st.session_state[_PAGE] = page
    st.rerun()


def current_page() -> str:
    init_state()
    return st.session_state[_PAGE]


def set_selected_company(m: Optional[CompanyMatch]) -> None:
    init_state()
    st.session_state[_COMPANY] = m


def get_selected_company() -> Optional[CompanyMatch]:
    init_state()
    return st.session_state[_COMPANY]


def set_public_data_result(r: Optional[PublicDataResult]) -> None:
    init_state()
    st.session_state[_PUBLIC] = r


def get_public_data_result() -> Optional[PublicDataResult]:
    init_state()
    return st.session_state[_PUBLIC]


def set_financials(f: CompanyFinancials) -> None:
    """Store the CONFIRMED data. Also clears any previous analysis."""
    init_state()
    st.session_state[_FINANCIALS] = f
    st.session_state[_ANALYSIS] = None


def get_financials() -> Optional[CompanyFinancials]:
    init_state()
    return st.session_state[_FINANCIALS]


def set_analysis(a: Optional[AnalysisResult]) -> None:
    init_state()
    st.session_state[_ANALYSIS] = a


def get_analysis() -> Optional[AnalysisResult]:
    init_state()
    return st.session_state[_ANALYSIS]


def set_llm_consent(v: bool) -> None:
    init_state()
    st.session_state[_CONSENT] = bool(v)


def get_llm_consent() -> bool:
    init_state()
    return bool(st.session_state[_CONSENT])


def reset_all() -> None:
    """Clear all app state back to defaults."""
    for key, default in _DEFAULTS.items():
        st.session_state[key] = default
