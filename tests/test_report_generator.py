from src import config
from src.ai_analyst import template_commentary
from src.report_generator import build_html_report
from tests.fixtures.sample_data import make_incomplete_financials
from tests.test_ai_analyst import analysis


def test_report_contains_screening_evidence_and_disclaimer():
    a = analysis(make_incomplete_financials(), 0.82)
    report = build_html_report(a, template_commentary(a))
    assert a.financials.company.name in report
    assert config.SCORE_DISCLAIMER in report
    assert config.INSUFFICIENT_SCORE_LABEL in report
    assert "Current ratio" in report
    assert "0.82x" in report
    assert "SYNTHETIC" in report
    assert "n/a" in report
    assert "Methodology and limitations" in report
    assert "Missing information" in report


def test_report_escapes_company_and_source_text():
    a = analysis(make_incomplete_financials())
    a.financials.company.name = '<script>alert("name")</script>'
    c = template_commentary(a)
    c.sources.append('<img src=x onerror=alert(1)>')
    report = build_html_report(a, c)
    assert "<script>" not in report
    assert "<img" not in report
    assert "&lt;script&gt;" in report
    assert "&lt;img" in report
    assert "<style>" in report
    assert 'src="http' not in report


def test_methodology_uses_the_scoring_owners_file(tmp_path, monkeypatch):
    from src import report_generator

    methodology = tmp_path / "methodology.md"
    methodology.write_text("Methodology owned by Person 4", encoding="utf-8")
    monkeypatch.setattr(report_generator, "METHODOLOGY", methodology)
    a = analysis(make_incomplete_financials())
    assert report_generator.methodology_text() == "Methodology owned by Person 4"
    report = build_html_report(a, template_commentary(a))
    assert "Methodology page in SolvIQ" in report
    assert "Ratios and screening scores are taken from the deterministic analysis engine." in report
    assert "Methodology owned by Person 4" not in report
    methodology.unlink()
    assert "The scoring methodology document has not been supplied" in build_html_report(a, template_commentary(a))


def test_dashboard_configures_html_download(monkeypatch):
    from unittest.mock import Mock
    from src.ui import dashboard_page

    button = Mock()
    monkeypatch.setattr(dashboard_page.st, "download_button", button)
    monkeypatch.setattr(dashboard_page, "section_header", Mock())
    a = analysis(make_incomplete_financials(), 0.82)
    dashboard_page._export(a, template_commentary(a))
    button.assert_called_once()
    args, kwargs = button.call_args
    assert args == ("Download Credit Analysis Report",)
    assert kwargs["file_name"].endswith(".html")
    assert kwargs["mime"] == "text/html"
    assert b"0.82x" in kwargs["data"]
