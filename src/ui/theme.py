"""Look and feel: CSS plus small UI helpers. Owned by Person 1."""
from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st

NAVY = "#0B1F3A"
TEAL = "#14B8A6"

_BADGE_COLORS = {
    "low": ("#DCFCE7", "#166534"),
    "medium": ("#FEF3C7", "#92400E"),
    "high": ("#FEE2E2", "#991B1B"),
    "info": ("#DBEAFE", "#1E40AF"),
}

_CSS = f"""
<style>
html, body, [class*="css"] {{ font-family: "Inter", "Segoe UI", Helvetica, Arial, sans-serif; }}
.block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px; }}
h1, h2, h3 {{ color: {NAVY}; letter-spacing: -0.01em; }}
[data-testid="stSidebar"] {{ background-color: {NAVY}; }}
[data-testid="stSidebar"] * {{ color: #FFFFFF; }}
[data-testid="stSidebar"] .stButton > button {{
    background: transparent; color: #FFFFFF; border: 1px solid rgba(255,255,255,0.4);
}}
[data-testid="stSidebar"] .stButton > button:hover {{ border-color: {TEAL}; color: {TEAL}; }}
.cr-card {{
    background: #FFFFFF; border: 1px solid #E2E8F0; border-left: 4px solid {TEAL};
    border-radius: 8px; padding: 1rem 1.2rem; margin-bottom: 0.8rem;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}}
.cr-card .cr-label {{ font-size: 0.8rem; color: #64748B; text-transform: uppercase;
    letter-spacing: 0.05em; }}
.cr-card .cr-value {{ font-size: 1.6rem; font-weight: 700; color: {NAVY}; }}
.cr-badge {{ display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; }}
.cr-section {{ margin: 1.6rem 0 0.8rem 0; padding-bottom: 0.4rem;
    border-bottom: 2px solid {TEAL}; }}
.cr-section h2 {{ margin: 0; font-size: 1.35rem; }}
.cr-section p {{ margin: 0.2rem 0 0 0; color: #64748B; }}
.cr-footer {{ margin-top: 3rem; padding-top: 0.8rem; border-top: 1px solid #E2E8F0;
    font-size: 0.78rem; color: #64748B; }}
</style>
"""


def apply_theme() -> None:
    """Inject the custom CSS. Call once near the top of app.py."""
    st.markdown(_CSS, unsafe_allow_html=True)


def metric_card_html(label: str, value: str, help: Optional[str] = None) -> str:
    """HTML for a metric card (text is escaped)."""
    title = f' title="{escape(help, quote=True)}"' if help else ""
    return (f'<div class="cr-card"{title}><div class="cr-label">{escape(label)}</div>'
            f'<div class="cr-value">{escape(value)}</div></div>')


def metric_card(label: str, value: str, help: Optional[str] = None) -> None:
    """Show a card with a small label and a large value."""
    st.markdown(metric_card_html(label, value, help), unsafe_allow_html=True)


def badge_html(text: str, kind: str = "info") -> str:
    """HTML for a pill badge; kind is low / medium / high / info."""
    bg, fg = _BADGE_COLORS.get(kind, _BADGE_COLORS["info"])
    return f'<span class="cr-badge" style="background:{bg};color:{fg}">{escape(text)}</span>'


def badge(text: str, kind: str = "info") -> None:
    """Show a coloured pill badge."""
    st.markdown(badge_html(text, kind), unsafe_allow_html=True)


def section_header(title: str, subtitle: Optional[str] = None) -> None:
    """Section title with a teal underline and optional subtitle."""
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="cr-section"><h2>{escape(title)}</h2>{sub}</div>',
                unsafe_allow_html=True)
