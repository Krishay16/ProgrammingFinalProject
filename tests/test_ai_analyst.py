from unittest.mock import patch

import pytest

from src.ai_analyst import ASSESSMENT, generate_commentary, template_commentary
from src.models import AnalysisResult, CreditScore, RatioResult, RatioStatus
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials


def analysis(financials, current_ratio=None):
    ratios = {}
    if current_ratio is not None:
        year = financials.latest().fiscal_year
        ratios[year] = {
            "current_ratio": RatioResult(
                key="current_ratio", label="Current ratio", category="liquidity",
                fiscal_year=year, value=current_ratio, status=RatioStatus.VALID,
                unit="x", formula="Current assets / current liabilities",
            )
        }
    return AnalysisResult(
        financials=financials, ratios=ratios, score=CreditScore(sufficient_data=False),
    )


@pytest.mark.parametrize("value, expected", [(1.62, "stronger"), (1.2, "some"), (0.82, "limited")])
def test_liquidity_is_conditioned_on_actual_results(value, expected):
    result = template_commentary(analysis(make_sample_financials(), value))
    assert f"{value:.2f}x" in result.liquidity
    assert expected in result.liquidity
    assert "Observation:" in result.liquidity
    assert "Interpretation:" in result.liquidity
    assert result.overall_assessment == ASSESSMENT


def test_incomplete_and_empty_inputs_explain_missing_evidence():
    financials = make_incomplete_financials()
    incomplete = template_commentary(analysis(financials))
    assert "SYNTHETIC" in incomplete.sources
    assert "Interest expense" in incomplete.missing_information
    assert "Free cash flow is unavailable" in incomplete.cash_flow
    assert not incomplete.positive_indicators
    empty = template_commentary(analysis(financials.model_copy(update={"periods": []})))
    assert "Confirmed annual financial statements." in empty.missing_information
    assert "did not return a full screening score" in empty.executive_summary


@pytest.mark.parametrize("consent", [False, True])
def test_local_commentary_never_calls_http(consent):
    with patch("requests.post") as post:
        result = generate_commentary(analysis(make_sample_financials()), consent)
    assert result.generated_by == "template"
    post.assert_not_called()


def test_net_cash_requires_negative_net_debt():
    a = analysis(make_sample_financials())
    year = a.financials.latest().fiscal_year
    a.ratios[year] = {
        key: RatioResult(key=key, label=key, category="leverage", fiscal_year=year,
                         value=value, status=RatioStatus.VALID, unit=unit, formula="Test fixture")
        for key, value, unit in (("net_debt_to_ebitda", -2, "x"), ("net_debt", 100, "currency"))
    }
    assert "net cash position" not in template_commentary(a).leverage
    a.ratios[year]["net_debt"].value = -100
    assert "net cash position" in template_commentary(a).leverage
