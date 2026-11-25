"""Owned by Person 5: Plotly figures."""
from __future__ import annotations

import plotly.graph_objects as go

from src.models import AnalysisResult, CreditScore


def revenue_chart(a: AnalysisResult) -> go.Figure:
    """Revenue by fiscal year."""
    raise NotImplementedError("Owned by Person 5, not built yet")


def margin_chart(a: AnalysisResult) -> go.Figure:
    """Operating and net margin by fiscal year."""
    raise NotImplementedError("Owned by Person 5, not built yet")


def debt_chart(a: AnalysisResult) -> go.Figure:
    """Total debt and net debt by fiscal year."""
    raise NotImplementedError("Owned by Person 5, not built yet")


def cash_flow_chart(a: AnalysisResult) -> go.Figure:
    """Operating cash flow, capex and free cash flow."""
    raise NotImplementedError("Owned by Person 5, not built yet")


def score_gauge(score: CreditScore) -> go.Figure:
    """0-100 gauge, or an 'Insufficient data' indicator."""
    raise NotImplementedError("Owned by Person 5, not built yet")
