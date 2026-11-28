"""Financial trend charts for the credit screening dashboard."""
from math import isfinite

import plotly.graph_objects as go

from src.config import RISK_BANDS
from src.models import AnalysisResult, CreditScore, RatioStatus

NAVY = "#0B1F3A"
TEAL = "#0F766E"
COLORS = (TEAL, NAVY, "#64748B")
BAND_COLORS = ("#FECACA", "#FED7AA", "#FDE68A", "#99F6E4")


def ratio_value(a: AnalysisResult, year: int, key: str) -> float | None:
    """Return a usable engine result, preserving reported zeroes."""
    ratio = a.ratios.get(year, {}).get(key)
    if ratio and ratio.status == RatioStatus.VALID:
        return ratio.value
    return None


def _trend(a, title, series, *, percent=False, bars=False):
    periods = {p.fiscal_year: p for p in a.financials.periods}
    years = range(min(periods), max(periods) + 1) if periods else []
    currencies = {p.currency for p in periods.values()}
    unit = "%" if percent else f"{next(iter(currencies), 'Currency')} millions"
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white", title=title, height=330,
        font=dict(color=NAVY), margin=dict(l=52, r=16, t=48, b=62),
        xaxis=dict(type="category", title="Fiscal year"),
        yaxis=dict(title=unit, ticksuffix="%" if percent else "", zeroline=True),
        legend=dict(orientation="h", y=-0.3), barmode="group",
    )
    if not percent and len(currencies) > 1:
        fig.update_yaxes(title_text="Reporting currency")
        fig.add_annotation(text="Periods use different currencies. Monetary trends are unavailable.",
                           x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        return fig

    has_values = False
    for (name, field, from_engine), color in zip(series, COLORS):
        values = []
        for year in years:
            period = periods.get(year)
            value = None
            if period is not None:
                value = ratio_value(a, year, field) if from_engine else period.get(field)
            if value is not None and isfinite(value):
                value = value * 100 if percent else value / 1_000_000
            else:
                value = None
            values.append(value)
        has_values |= any(value is not None for value in values)
        args = dict(name=name, x=[f"FY {year}" for year in years], y=values,
                    marker_color=color, hovertemplate=f"%{{x}}<br>%{{y:,.2f}} {unit}<extra></extra>")
        if bars:
            fig.add_bar(**args)
        else:
            fig.add_scatter(**args, mode="lines+markers", line=dict(color=color),
                            connectgaps=False)
    if not has_values:
        fig.add_annotation(text="No financial values available", x=0.5, y=0.5,
                           xref="paper", yref="paper", showarrow=False)
    return fig


def revenue_chart(a: AnalysisResult) -> go.Figure:
    """Show reported revenue by fiscal year."""
    return _trend(a, "Revenue", [("Revenue", "revenue", False)], bars=True)


def margin_chart(a: AnalysisResult) -> go.Figure:
    """Show operating and net profit margins from the engine."""
    return _trend(a, "Profit margins", [
        ("Operating margin", "operating_margin", True),
        ("Net profit margin", "net_profit_margin", True),
    ], percent=True)


def debt_chart(a: AnalysisResult) -> go.Figure:
    """Show total and net debt from the engine."""
    return _trend(a, "Debt position", [
        ("Total debt", "total_debt", True), ("Net debt", "net_debt", True),
    ], bars=True)


def cash_flow_chart(a: AnalysisResult) -> go.Figure:
    """Show operating cash flow, CapEx outflow magnitude and free cash flow."""
    return _trend(a, "Cash flow", [
        ("Operating cash flow", "operating_cash_flow", False),
        ("CapEx (outflow)", "capex", False),
        ("Free cash flow", "free_cash_flow", True),
    ], bars=True)


def score_gauge(score: CreditScore) -> go.Figure:
    """Show the engine score and the configured risk bands when available."""
    fig = go.Figure()
    fig.update_layout(template="plotly_white", height=230,
                      margin=dict(l=24, r=24, t=30, b=15), font=dict(color=NAVY))
    if score.total is None or not isfinite(score.total):
        fig.add_annotation(text="Insufficient data", x=0.5, y=0.5, xref="paper",
                           yref="paper", showarrow=False, font=dict(color="#64748B", size=22))
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        return fig
    bands = sorted(RISK_BANDS)
    bounds = [threshold for threshold, _ in bands] + [100]
    steps = [
        dict(range=[lower, upper], color=color)
        for lower, upper, color in zip(bounds, bounds[1:], BAND_COLORS)
    ]
    fig.add_indicator(
        mode="gauge+number", value=score.total, number=dict(suffix=" / 100", valueformat=".3~f"),
        gauge=dict(axis=dict(range=[0, 100], tickvals=bounds),
                   bar=dict(color=NAVY), steps=steps),
    )
    return fig
