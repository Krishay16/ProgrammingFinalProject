"""Verify chart outputs against the official synthetic financial fixtures."""
import plotly.graph_objects as go
import pytest

from src.charts import cash_flow_chart, debt_chart, margin_chart, revenue_chart, score_gauge
from src.engine import run_analysis
from src.models import AnalysisResult, CompanyFinancials, CreditScore, RatioResult, RatioStatus
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials


def _analysis(financials: CompanyFinancials) -> AnalysisResult:
    """Temporary test-only adapter for the foundation engine stub."""
    try:
        return run_analysis(financials)
    except NotImplementedError:
        # Supply one example engine result using the fixture's reported EBIT and revenue.
        ratios = {}
        for period in financials.periods:
            ebit, revenue = period.get("ebit"), period.get("revenue")
            value = ebit / revenue if ebit is not None and revenue else None
            ratios[period.fiscal_year] = {
                "operating_margin": RatioResult(
                    key="operating_margin", label="Operating margin", category="profitability",
                    fiscal_year=period.fiscal_year, value=value,
                    status=RatioStatus.VALID if value is not None else RatioStatus.UNAVAILABLE,
                    unit="%", formula="EBIT / Revenue",
                )
            }
        return AnalysisResult(
            financials=financials, ratios=ratios, score=CreditScore(sufficient_data=False),
        )


def _empty() -> CompanyFinancials:
    financials = make_sample_financials()
    return financials.model_copy(update={"periods": []})


@pytest.mark.parametrize("fixture", [make_sample_financials, make_incomplete_financials, _empty])
def test_each_chart_returns_figure(fixture):
    analysis = _analysis(fixture())
    for chart in (revenue_chart, margin_chart, debt_chart, cash_flow_chart):
        assert isinstance(chart(analysis), go.Figure)
    assert isinstance(score_gauge(analysis.score), go.Figure)


def test_missing_cash_flows_are_gaps():
    fig = cash_flow_chart(_analysis(make_incomplete_financials()))
    assert [list(trace.y) for trace in fig.data] == [[None], [None], [None]]


def test_revenue_distinguishes_a_missing_year_from_true_zero():
    financials = make_sample_financials()
    recent, middle, old = financials.periods
    recent.revenue.value = 0
    financials.periods = [recent, old]
    trace = revenue_chart(_analysis(financials)).data[0]
    assert list(trace.x) == [f"FY {p.fiscal_year}" for p in (old, middle, recent)]
    assert list(trace.y) == [old.revenue.value / 1_000_000, None, 0]


def test_margin_uses_engine_result_and_percent_scale():
    analysis = _analysis(make_sample_financials())
    chart = margin_chart(analysis)
    years = sorted(analysis.ratios)
    expected = [analysis.ratios[year]["operating_margin"].value * 100 for year in years]
    assert list(chart.data[0].y) == pytest.approx(expected)
    assert chart.data[0].connectgaps is False


def test_gauge_distinguishes_zero_score_from_no_score():
    absent = score_gauge(CreditScore(sufficient_data=False))
    assert not absent.data
    assert absent.layout.annotations[0].text == "Insufficient data"
    zero = score_gauge(CreditScore(total=0, sufficient_data=True))
    assert zero.data[0].value == 0
    assert len(zero.data[0].gauge.steps) == 4


def test_mixed_currency_amounts_are_not_compared():
    financials = make_sample_financials()
    financials.periods[0].currency = "EUR"
    chart = revenue_chart(_analysis(financials))
    assert not chart.data
    assert "different currencies" in chart.layout.annotations[0].text
