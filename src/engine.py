"""Single entry point for the SolvIQ analysis. Owned by Person 4.

run_analysis = validation (Person 1) + ratios + illustrative score + alerts.
Missing data is handled explicitly by every step, so ordinary gaps never raise. There is
deliberately no catch-all try/except: a coding bug must fail the tests, not hide.
"""
from __future__ import annotations

from src.credit_scoring import compute_credit_score
from src.data_validation import validate_financials
from src.financial_calculations import compute_all_ratios
from src.models import AnalysisResult, CompanyFinancials
from src.risk_alerts import generate_alerts


def run_analysis(f: CompanyFinancials) -> AnalysisResult:
    """Validate, compute all ratios, score the latest year and generate alerts.

    An empty CompanyFinancials (no periods) returns an insufficient score, no ratios, no
    alerts and the validation error explaining why.
    """
    issues = validate_financials(f)
    ratios = compute_all_ratios(f)
    return AnalysisResult(
        financials=f,
        ratios=ratios,
        score=compute_credit_score(ratios, f),
        alerts=generate_alerts(ratios, f),
        validation_issues=issues,
    )
