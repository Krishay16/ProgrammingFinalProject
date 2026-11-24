"""Streamlit entry point and navigation. Owned by Person 1.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import importlib

import streamlit as st

from src import config, state
from src.ui.theme import apply_theme

# Page name -> module that exposes render() -> None
PAGE_MODULES = {
    "Search": "src.ui.search_page",
    "Upload PDF": "src.ui.upload_page",
    "Manual Entry": "src.ui.manual_page",
    "Dashboard": "src.ui.dashboard_page",
    "Stress Scenario": "src.ui.scenario_page",
    "Methodology": "src.ui.methodology_page",
}


def _load_demo_company() -> None:
    """Load the SYNTHETIC demo company so pages can be tested without real data."""
    try:
        from tests.fixtures.sample_data import make_sample_financials
        state.set_financials(make_sample_financials())
    except Exception as exc:  # never let the demo button break the app
        st.sidebar.error(f"Could not load the demo company ({type(exc).__name__}).")


def _sidebar() -> None:
    with st.sidebar:
        st.markdown(f"## {config.APP_NAME}")
        st.caption(config.TAGLINE)

        current = state.current_page()
        choice = st.radio("Navigation", config.PAGES, index=config.PAGES.index(current),
                          label_visibility="collapsed")
        if choice != current:
            state.go_to(choice)

        st.divider()
        st.markdown("**Data in use**")
        f = state.get_financials()
        if f is None:
            st.caption("No company loaded")
        else:
            years = ", ".join(f"FY{p.fiscal_year}" for p in f.periods) or "no periods"
            st.caption(f"{f.company.name}\n\nSource: {f.source_type.value}\n\n{years}")
            if f.source_type.value == "synthetic":
                st.caption("SYNTHETIC demo data, not a real company.")

        st.divider()
        if st.button("Load SYNTHETIC demo company", use_container_width=True):
            _load_demo_company()
            st.rerun()
        if st.button("Reset", use_container_width=True):
            state.reset_all()
            st.rerun()


def _render_page(page: str) -> None:
    """Render one page; an unexpected error must never break the whole app."""
    try:
        module = importlib.import_module(PAGE_MODULES[page])
        module.render()
    except Exception as exc:
        st.error("Something went wrong on this page. You can switch pages or press Reset in "
                 "the sidebar and try again.")
        with st.expander("Technical details"):
            st.write(f"{type(exc).__name__}: {exc}")


def main() -> None:
    st.set_page_config(page_title=config.APP_NAME, layout="wide")
    state.init_state()
    apply_theme()
    _sidebar()
    _render_page(state.current_page())
    st.markdown(f'<div class="cr-footer">{config.SCORE_DISCLAIMER}</div>',
                unsafe_allow_html=True)


main()
