"""Present the confirmed financials and the deterministic screening results."""
import re
from math import isfinite

import streamlit as st

from src import config, engine, state
from src.ai_analyst import CreditCommentary, generate_commentary
from src.charts import cash_flow_chart, debt_chart, margin_chart, ratio_value, revenue_chart, score_gauge
from src.models import ALL_FIELDS, FIELD_LABELS, AnalysisResult, RatioStatus, SourceType
from src.report_generator import build_html_report
from src.ui.theme import badge, metric_card, section_header
from src.financial_calculations import ebitda_value

SOURCE_LABELS = {
    SourceType.SEC_EDGAR: "SEC EDGAR", SourceType.PDF: "PDF",
    SourceType.MANUAL: "Manual entry", SourceType.SYNTHETIC: "SYNTHETIC",
}
CATEGORIES = ("liquidity", "leverage", "profitability", "coverage", "cash_flow", "growth")


def _format(value: float | None, unit: str, currency: str = "") -> str:
    if value is None or not isfinite(value):
        return "n/a"
    if unit == "%":
        return f"{value:.1%}"
    if unit == "x":
        return f"{value:,.2f}x"
    if unit == "currency":
        return f"{currency} {value / 1_000_000:,.2f}m".strip()
    return f"{value:,.2f}"


def _overview(a: AnalysisResult) -> None:
    section_header("Credit Health Overview")
    score = a.score
    if score.total is None:
        st.info(config.INSUFFICIENT_SCORE_LABEL)
    else:
        st.plotly_chart(score_gauge(score), use_container_width=True)
        if score.category:
            st.text(score.category)
    st.caption(config.SCORE_DISCLAIMER)
    if a.financials.company.is_financial_institution:
        st.warning(config.FINANCIAL_INSTITUTION_MESSAGE)
    with st.expander("Score breakdown"):
        if score.explanation:
            st.text(score.explanation)
        for factor in score.factors:
            points = "n/a" if factor.points is None else f"{factor.points:g}"
            st.text(f"{factor.factor.replace('_', ' ').title()} · {points} / {factor.max_points:g}")
            if factor.explanation:
                st.text(factor.explanation)
        if not score.factors:
            st.info("No factors were scored.")
        for threshold, category in sorted(config.RISK_BANDS, reverse=True):
            st.text(f"From {threshold}/100 · {category}")
    period = a.financials.latest()
    if period is None:
        return
    year = period.fiscal_year
    ebitda, ebitda_note = ebitda_value(period)
    metrics = [
        ("Revenue", period.get("revenue")),
        ("EBITDA (derived)" if ebitda_note else "EBITDA", ebitda) if ebitda is not None else ("EBIT", period.get("ebit")),
        ("Total debt", ratio_value(a, year, "total_debt")),
        ("Net debt", ratio_value(a, year, "net_debt")),
    ]
    st.caption(f"FY {year} · {period.currency} millions")
    for column, (label, value) in zip(st.columns(4), metrics):
        with column:
            metric_card(label, _format(value, "currency", period.currency))


def _ratios(a: AnalysisResult) -> None:
    section_header("Financial Ratios")
    periods = {p.fiscal_year: p.currency for p in a.financials.periods}
    if not any(a.ratios.values()):
        st.info("No financial ratios are available.")
        return
    for category in CATEGORIES:
        labels = {
            ratio.key: ratio.label
            for ratios in a.ratios.values()
            for ratio in ratios.values()
            if ratio.category == category
        }
        if not labels:
            continue
        st.subheader(category.replace("_", " ").title())
        rows = []
        years = sorted(periods.keys() | a.ratios.keys(), reverse=True)
        for key, label in labels.items():
            row = {"Metric": label}
            for year in years:
                ratio = a.ratios.get(year, {}).get(key)
                row[f"FY {year}"] = _format(ratio_value(a, year, key), ratio.unit, periods.get(year, "")) if ratio else "n/a"
            rows.append(row)
        st.dataframe(rows, hide_index=True, use_container_width=True)
        for key, label in labels.items():
            with st.expander(f"{label} · How was this calculated?"):
                for year in years:
                    ratio = a.ratios.get(year, {}).get(key)
                    if ratio is None:
                        st.text(f"FY {year} · n/a · No calculation was supplied.")
                        continue
                    st.text(f"FY {year} · {ratio.formula}")
                    if ratio.explanation:
                        st.text(ratio.explanation)
                    elif ratio.status != RatioStatus.VALID:
                        st.text(f"n/a · {ratio.status.value.capitalize()}")
                    if ratio.inputs:
                        st.dataframe([
                            {"Input": FIELD_LABELS.get(field, field.replace("_", " ").capitalize()),
                             "Value": "n/a" if value is None else _format(value, "currency", periods.get(year, "")),
                             "Currency": periods.get(year, "")}
                            for field, value in ratio.inputs.items()
                        ], hide_index=True, use_container_width=True)


def _trends(a: AnalysisResult) -> None:
    section_header("Financial Trends")
    for left, right in ((revenue_chart, margin_chart), (debt_chart, cash_flow_chart)):
        for column, chart in zip(st.columns(2), (left, right)):
            with column:
                st.plotly_chart(chart(a), use_container_width=True)


def _alerts(a: AnalysisResult) -> None:
    section_header("Credit Risk Alerts")
    currencies = {p.fiscal_year: p.currency for p in a.financials.periods}
    if not a.alerts:
        st.info("No screening alerts were triggered by the configured rules.")
    for alert in a.alerts:
        with st.container(border=True):
            badge(alert.severity.value.title(), alert.severity.value)
            st.text(alert.title)
            ratio = a.ratios.get(alert.fiscal_year, {}).get(alert.indicator)
            if ratio is not None:
                unit = ratio.unit
            elif alert.indicator == "total_equity":
                unit = "currency"
            elif alert.indicator == "key_inputs":
                unit = "count"
            else:
                unit = ""

            if unit == "count" and alert.measured_value is not None:
                measured = f"{alert.measured_value:.0f}"
            else:
                measured = _format(
                    alert.measured_value,
                    unit,
                    currencies.get(alert.fiscal_year, "")
                )
            st.text(f"Observed {measured} · Threshold {alert.threshold}")
            with st.expander("Interpretation and source"):
                st.text(alert.interpretation)
                st.text(f"FY {alert.fiscal_year}")
                st.text(alert.source_reference or "No source reference supplied.")


def _quality(a: AnalysisResult) -> None:
    section_header("Data Quality and Sources")
    f = a.financials
    st.text(SOURCE_LABELS[f.source_type])
    for period in f.periods:
        missing = period.missing_fields()
        complete = (len(ALL_FIELDS) - len(missing)) / len(ALL_FIELDS)
        st.text(f"FY {period.fiscal_year} · {period.currency} · {complete:.0%} of statement fields present")
        if missing:
            st.text("Missing: " + ", ".join(FIELD_LABELS[field] for field in missing))
        references = {
            (p.source_ref, p.location or "", str(p.filing_date or period.filing_date or ""))
            for field in ALL_FIELDS
            if (p := getattr(period, field).provenance) and p.source_ref
        }
        if references:
            with st.expander(f"FY {period.fiscal_year} source documents"):
                for reference, location, filed in sorted(references):
                    st.text(" · ".join(filter(None, (reference, location, f"Filed {filed}" if filed else ""))))
        else:
            st.caption("No field-level source documents recorded.")
    for warning in f.warnings:
        st.warning(warning)
    for issue in a.validation_issues:
        prefix = f"FY {issue.fiscal_year} · " if issue.fiscal_year is not None else ""
        {"error": st.error, "warning": st.warning, "info": st.info}[issue.level](prefix + issue.message)
    for year, ratios in sorted(a.ratios.items(), reverse=True):
        notes = [
            f"{r.label} · {r.explanation or r.status.value.capitalize()}"
            for r in ratios.values() if r.explanation or r.status != RatioStatus.VALID
        ]
        if notes:
            with st.expander(f"FY {year} calculation notes"):
                for note in notes:
                    st.text(note)


def _commentary(c: CreditCommentary) -> None:
    section_header("AI Credit Analysis")
    st.caption("Generated by a deterministic, rule-based template. LLM integration is designed but not enabled.")
    for title, value in (
        ("Executive Summary", c.executive_summary), ("Liquidity", c.liquidity),
        ("Leverage", c.leverage), ("Profitability", c.profitability),
        ("Cash Flow", c.cash_flow), ("Key Risks", c.key_risks),
        ("Positive Indicators", c.positive_indicators), ("Overall Assessment", c.overall_assessment),
    ):
        st.subheader(title)
        if isinstance(value, list):
            fallback = (
                "No screening alerts were triggered."
                if title == "Key Risks"
                else "No indicators identified from the available results."
            )
            for item in value or [fallback]:
                st.text(item)
        else:
            st.text(value)
    with st.expander("Missing information and sources"):
        for title, items in (("Missing information", c.missing_information), ("Sources", c.sources)):
            st.subheader(title)
            for item in items or ["None listed."]:
                st.text(item)


def _export(analysis: AnalysisResult, commentary: CreditCommentary) -> None:
    section_header("Export")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", analysis.financials.company.name).strip("_-")[:80] or "company"
    st.download_button(
        "Download Credit Analysis Report",
        data=build_html_report(analysis, commentary).encode("utf-8"),
        file_name=f"{slug}_credit_screening_{analysis.generated_at.date().isoformat()}.html",
        mime="text/html",
    )


def render() -> None:
    """Render the dashboard for the current confirmed company."""
    st.title(config.APP_NAME)
    financials = state.get_financials()
    if financials is None:
        st.info("Load a company or confirm financial statements to start screening.")
        for column, page in zip(st.columns(3), ("Search", "Upload PDF", "Manual Entry")):
            with column:
                if st.button(page):
                    state.go_to(page)
        return

    company = financials.company
    st.text(f"{company.name} ({company.ticker})" if company.ticker else company.name)
    if financials.source_type == SourceType.SYNTHETIC:
        badge("SYNTHETIC", "info")
    st.text(SOURCE_LABELS[financials.source_type])
    for period in financials.periods:
        end = str(period.period_end) if period.period_end else "period end unavailable"
        st.text(f"FY {period.fiscal_year} · {end} · {period.currency}")

    analysis = state.get_analysis()
    if analysis is None:
        try:
            analysis = engine.run_analysis(financials)
        except NotImplementedError:
            st.info("The analysis engine is not available in this build.")
            return
        state.set_analysis(analysis)

    _overview(analysis)
    _ratios(analysis)
    _trends(analysis)
    _alerts(analysis)
    commentary = generate_commentary(analysis, allow_external_llm=False)
    _commentary(commentary)
    _quality(analysis)
    _export(analysis, commentary)
