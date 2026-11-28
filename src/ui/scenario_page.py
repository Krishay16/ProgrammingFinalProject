"""Stress Scenario page. Owned by Person 4.

Four sliders and three presets drive src.scenario.run_scenario on the CONFIRMED financials
(state.get_financials()). Reported and stressed ratios and scores are shown side by side.

Session state: app data is read only through src/state.py helpers. The only direct
st.session_state use is for this page's own widget keys, all prefixed "p4_scenario_",
which the preset buttons set before the sliders are drawn.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from src import config, state
from src.credit_scoring import FACTOR_LABELS, fmt_money, fmt_value
from src.models import CreditScore, RatioResult, RatioStatus
from src.scenario import MAX_CHANGE, MIN_CHANGE, ScenarioInputs, ScenarioResult, run_scenario
from src.ui.theme import section_header

_KEY_PREFIX = "p4_scenario_"
# slider name -> (widget key, label, ScenarioInputs field)
SLIDERS: dict[str, tuple[str, str, str]] = {
    "revenue": (f"{_KEY_PREFIX}revenue", "Revenue change (%)", "revenue_change_pct"),
    "ebit": (f"{_KEY_PREFIX}ebit", "EBIT change (%)", "ebit_change_pct"),
    "debt": (f"{_KEY_PREFIX}debt", "Debt change (%)", "debt_change_pct"),
    "interest": (f"{_KEY_PREFIX}interest", "Interest expense change (%)",
                 "interest_change_pct"),
}
# preset label -> slider values in whole percent (sliders not listed are reset to 0)
PRESETS: dict[str, dict[str, int]] = {
    "EBIT -20%": {"ebit": -20},
    "Revenue -10% and EBIT -25%": {"revenue": -10, "ebit": -25},
    "Debt +30%": {"debt": 30},
}
KEY_RATIOS: list[str] = ["current_ratio", "debt_to_equity", "net_debt", "net_debt_to_ebitda",
                         "operating_margin", "interest_coverage", "fcf_margin",
                         "revenue_growth", "total_debt"]


# --------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------
def _fmt_ratio(r: Optional[RatioResult], currency: str) -> str:
    if r is None:
        return "n/a"
    if r.status != RatioStatus.VALID or r.value is None:
        return r.status.value.capitalize()
    if r.unit == "currency":
        return fmt_money(r.value, currency)
    return fmt_value(r.value, r.unit)


def _fmt_change(base: Optional[RatioResult], new: Optional[RatioResult],
                currency: str) -> str:
    """Stressed minus reported, in the ratio's own unit (percentage points for %)."""
    if base is None or new is None or base.value is None or new.value is None:
        return "-"
    diff = new.value - base.value
    if base.unit == "currency":
        return ("+" if diff > 0 else "") + fmt_money(diff, currency)
    if base.unit == "%":
        return f"{diff * 100:+.1f} pp"
    return f"{diff:+.2f}x"


def _fmt_score(score: CreditScore) -> tuple[str, str]:
    """(big value, caption) for a score metric."""
    if score.total is None:
        return "Insufficient data", config.INSUFFICIENT_SCORE_LABEL
    return f"{score.total:g} / 100", score.category or ""


# --------------------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------------------
def _apply_preset(values: dict[str, int]) -> None:
    """Button callback: set every slider (runs before the sliders are drawn)."""
    for name, (key, _, _) in SLIDERS.items():
        st.session_state[key] = values.get(name, 0)


def _inputs() -> ScenarioInputs:
    st.markdown("**Presets**")
    cols = st.columns(len(PRESETS) + 1)
    for col, (label, values) in zip(cols, PRESETS.items()):
        col.button(label, key=f"{_KEY_PREFIX}preset_{label}", on_click=_apply_preset,
                   args=(values,), use_container_width=True)
    cols[-1].button("Reset to 0%", key=f"{_KEY_PREFIX}preset_reset", on_click=_apply_preset,
                    args=({},), use_container_width=True)

    lo, hi = int(MIN_CHANGE * 100), int(MAX_CHANGE * 100)
    values: dict[str, float] = {}
    cols = st.columns(2)
    for i, (key, label, field) in enumerate(SLIDERS.values()):
        if key not in st.session_state:  # seed 0% once; presets then set the key
            st.session_state[key] = 0
        pct = cols[i % 2].slider(label, min_value=lo, max_value=hi, step=1, key=key)
        values[field] = pct / 100
    return ScenarioInputs(**values)


def _ratio_table(result: ScenarioResult, currency: str) -> pd.DataFrame:
    fy = result.stressed_period.fiscal_year
    rows = []
    for key in KEY_RATIOS:
        base, new = result.base.get(key), result.stressed.get(key)
        rows.append({
            "Ratio": (base or new).label if (base or new) else key,
            f"Reported (FY{fy})": _fmt_ratio(base, currency),
            "Stressed scenario": _fmt_ratio(new, currency),
            "Change": _fmt_change(base, new, currency),
        })
    return pd.DataFrame(rows)


def _scores(result: ScenarioResult) -> None:
    fy = result.stressed_period.fiscal_year
    base_value, base_caption = _fmt_score(result.base_score)
    new_value, new_caption = _fmt_score(result.stressed_score)
    delta = None
    if result.base_score.total is not None and result.stressed_score.total is not None:
        delta = f"{result.stressed_score.total - result.base_score.total:+g} points"
    c1, c2 = st.columns(2)
    c1.metric(f"Reported score (FY{fy})", base_value)
    c1.caption(base_caption)
    c2.metric("Stressed scenario score", new_value, delta=delta)
    c2.caption(new_caption)
    if not result.stressed_score.sufficient_data:
        st.info(result.stressed_score.explanation)


def _factor_chart(result: ScenarioResult) -> None:
    """Simple bar chart of factor points (only factors scored in both cases)."""
    base = {fs.factor: fs.points for fs in result.base_score.factors}
    new = {fs.factor: fs.points for fs in result.stressed_score.factors}
    rows = {FACTOR_LABELS[k]: {"Reported": base[k], "Stressed": new.get(k)}
            for k in base if base[k] is not None and new.get(k) is not None}
    if not rows:
        st.caption("No factor could be scored in both cases, so there is nothing to chart.")
        return
    st.markdown("**Factor points (reported vs stressed)**")
    st.bar_chart(pd.DataFrame(rows).T, stack=False)


# --------------------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------------------
def render() -> None:
    """Stress Scenario page."""
    section_header("Stress Scenario", "Apply simple shocks to the latest reported year.")
    st.warning(f"**{config.SCENARIO_LABEL}**")

    f = state.get_financials()
    if f is None:
        st.info("No confirmed financial data yet. Search for a company (or upload / enter "
                "figures) and confirm the data first.")
        if st.button("Go to Search", key=f"{_KEY_PREFIX}goto_search"):
            state.go_to("Search")
        return
    if not f.periods:
        st.info("The confirmed data contains no financial periods, so there is nothing to "
                "stress. Add at least one fiscal year on the Manual Entry page.")
        return
    if f.company.is_financial_institution:
        st.info(config.FINANCIAL_INSTITUTION_MESSAGE)

    st.caption(f"{f.company.name} · source: {f.source_type.value}")
    s = _inputs()
    try:
        result = run_scenario(f, s)
    except ValueError as exc:  # the only expected failure: no periods to stress
        st.error(f"The scenario could not be run: {exc}")
        return

    currency = result.stressed_period.currency
    st.markdown(f"**Key ratios ({currency})**")
    st.dataframe(_ratio_table(result, currency), hide_index=True, use_container_width=True)
    _scores(result)
    _factor_chart(result)

    st.markdown("**Assumptions and simplifications**")
    st.markdown("\n".join(f"- {a}" for a in result.assumptions))
    st.caption(config.SCORE_DISCLAIMER)
