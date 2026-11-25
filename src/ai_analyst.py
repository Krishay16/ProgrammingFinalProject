"""Owned by Person 5: credit commentary (template by default, optional LLM)."""
from __future__ import annotations

from pydantic import BaseModel

from src.models import AnalysisResult


class CreditCommentary(BaseModel):
    """TODO(Person 5): executive_summary, liquidity, leverage, profitability, cash_flow,
    key_risks, positive_indicators, overall_assessment, missing_information, sources,
    generated_by, notes."""


def generate_commentary(a: AnalysisResult, allow_external_llm: bool) -> CreditCommentary:
    """Template commentary unless an LLM is configured AND allowed."""
    raise NotImplementedError("Owned by Person 5, not built yet")
