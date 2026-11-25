"""Tests for src/engine.py. Owned by Person 4.

run_analysis on both SYNTHETIC fixtures and on empty / all-missing companies.
"""
from __future__ import annotations

from src import config
from src.engine import run_analysis
from src.financial_calculations import STANDARD_RATIO_KEYS
from src.models import (AnalysisResult, CompanyFinancials, CompanyInfo, FinancialPeriod,
                        Severity, SourceType)
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials


def test_healthy_sample():
    a = run_analysis(make_sample_financials())
    assert isinstance(a, AnalysisResult)
    assert sorted(a.ratios) == [2022, 2023, 2024]
    for year_ratios in a.ratios.values():
        assert list(year_ratios) == STANDARD_RATIO_KEYS  # all 15 keys every year
    # 15 + 21.875 + 20 + 20 + 15 = 91.875 (see tests/test_credit_scoring.py)
    assert a.score.total == 91.875
    assert a.score.category == "Lower Indicative Financial Risk"
    assert a.alerts == []
    assert not [i for i in a.validation_issues if i.level == "error"]


def test_incomplete_sample():
    a = run_analysis(make_incomplete_financials())
    assert a.score.sufficient_data is False and a.score.total is None
    assert [fs.points for fs in a.score.factors] == [5.0, 0.0, 10.0, None, None]
    assert [(x.indicator, x.severity) for x in a.alerts] == [
        ("current_ratio", Severity.MEDIUM), ("total_equity", Severity.HIGH),
        ("key_inputs", Severity.HIGH)]
    assert any("Negative equity" in i.message for i in a.validation_issues)


def test_empty_company_does_not_raise():
    f = CompanyFinancials(company=CompanyInfo(name="Empty (SYNTHETIC)"),
                          source_type=SourceType.SYNTHETIC)
    a = run_analysis(f)
    assert a.ratios == {}
    assert a.alerts == []
    assert a.score.sufficient_data is False and a.score.total is None
    assert a.score.explanation.startswith(config.INSUFFICIENT_SCORE_LABEL)
    assert any(i.level == "error" and "No financial periods" in i.message
               for i in a.validation_issues)


def test_period_with_every_value_missing_does_not_raise():
    f = CompanyFinancials(company=CompanyInfo(name="Blank (SYNTHETIC)"),
                          source_type=SourceType.SYNTHETIC,
                          periods=[FinancialPeriod(fiscal_year=2024)])
    a = run_analysis(f)
    assert all(fs.points is None for fs in a.score.factors)
    assert a.score.total is None
    # 12 key inputs missing -> one HIGH data-quality alert, nothing else
    assert [(x.alert_type, x.severity, x.measured_value) for x in a.alerts] == [
        ("data_quality", Severity.HIGH, 12)]
    assert any(i.level == "error" for i in a.validation_issues)


def test_financial_institution():
    f = make_sample_financials()
    f.company.is_financial_institution = True
    a = run_analysis(f)
    assert a.score.total is None
    assert a.score.explanation == config.FINANCIAL_INSTITUTION_MESSAGE
    assert a.alerts == []
