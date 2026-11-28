"""Build a standalone, printable preliminary screening report."""
from html import escape
from pathlib import Path

from src import config
from src.ai_analyst import CreditCommentary
from src.models import ALL_FIELDS, FIELD_LABELS, AnalysisResult, RatioStatus

METHODOLOGY = Path(__file__).resolve().parents[1] / "docs" / "methodology.md"
STYLE = """
*{box-sizing:border-box}body{max-width:980px;margin:2rem auto;padding:0 1.1rem;
font:15px/1.5 system-ui,sans-serif;color:#0b1f3a}
header{background:#0b1f3a;color:#fff;padding:1.75rem;border-bottom:5px solid #14b8a6}
h1,h2,h3{line-height:1.2}h2{border-bottom:1px solid #badbd8;padding-bottom:.35rem}
section{margin:1.5rem 0}table{border-collapse:collapse;width:100%;margin-bottom:1rem}
th,td{text-align:left;padding:.45rem;border-bottom:1px solid #d5e0e6}
th{background:#e8f4f3}pre{white-space:pre-wrap;font:inherit;overflow-wrap:anywhere}
li,td{overflow-wrap:anywhere}.subtle{color:#465a6d}
@media print{body{margin:0}header{background:white;color:#0b1f3a}
h2,h3{break-after:avoid}tr{break-inside:avoid}thead{display:table-header-group}}
"""


def methodology_text() -> str | None:
    """Read the scoring owner's methodology when it is present."""
    try:
        return METHODOLOGY.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _paragraph(value: object) -> str:
    return f"<p>{_text(value)}</p>"


def _list(values: list[str], fallback: str) -> str:
    return "<ul>" + "".join(f"<li>{_text(v)}</li>" for v in values or [fallback]) + "</ul>"


def _table(headers, rows) -> str:
    head = "".join(f'<th scope="col">{_text(v)}</th>' for v in headers)
    body = "".join("<tr>" + "".join(f"<td>{_text(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _amount(value: float | None, currency: str) -> str:
    return "n/a" if value is None else f"{currency} {value / 1e6:,.2f}m".strip()


def _ratio(ratio, currency) -> str:
    if ratio.status != RatioStatus.VALID or ratio.value is None:
        return f"n/a — {ratio.explanation or ratio.status.value}"
    if ratio.unit == "%":
        return f"{ratio.value:.1%}"
    if ratio.unit == "x":
        return f"{ratio.value:.2f}x"
    return _amount(ratio.value, currency)


def build_html_report(a: AnalysisResult, c: CreditCommentary) -> str:
    """Render the confirmed data and analysis as escaped HTML with inline CSS."""
    f = a.financials
    title = f"{config.APP_NAME} Preliminary Credit Screening Report"
    score = a.score
    currency_by_year = {p.fiscal_year: p.currency for p in f.periods}
    score_text = config.INSUFFICIENT_SCORE_LABEL if score.total is None else f"{score.total:g} / 100"
    out = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_text(title)}</title><style>{STYLE}</style><body>",
        f"<header><h1>{_text(title)}</h1>{_paragraph(f.company.name)}</header>",
        "<section><h2>Company and reporting periods</h2>",
        _paragraph(f"Ticker: {f.company.ticker or 'n/a'} · Source: {f.source_type.value.replace('_', ' ').upper()}"),
        _paragraph(f"Generated: {a.generated_at.date().isoformat()}"),
        _table(("Fiscal year", "Period start", "Period end", "Currency", "Filing date"),
               [(p.fiscal_year, p.period_start or "n/a", p.period_end or "n/a",
                 p.currency, p.filing_date or "n/a") for p in f.periods]),
        "</section><section><h2>Credit health overview</h2>",
        _paragraph(score_text), _paragraph(score.category or score.explanation),
        _paragraph(config.SCORE_DISCLAIMER),
    ]
    if f.company.is_financial_institution:
        out.append(_paragraph(config.FINANCIAL_INSTITUTION_MESSAGE))
    if score.factors:
        out.append(_table(("Factor", "Points", "Maximum", "Explanation"), [
            (factor.factor.replace("_", " ").title(), factor.points if factor.points is not None else "n/a",
             factor.max_points, factor.explanation) for factor in score.factors
        ]))
    if p := f.latest():
        ratios = a.ratios.get(p.fiscal_year, {})
        out.append(_table(("Metric", f"FY {p.fiscal_year}"), [
            ("Revenue", _amount(p.get("revenue"), p.currency)),
            ("EBITDA", _amount(p.get("ebitda"), p.currency)),
            ("EBIT", _amount(p.get("ebit"), p.currency)),
            ("Total debt", _ratio(ratios["total_debt"], p.currency) if "total_debt" in ratios else "n/a"),
            ("Net debt", _ratio(ratios["net_debt"], p.currency) if "net_debt" in ratios else "n/a"),
        ]))
    out.append("</section><section><h2>Historical financial ratios</h2>")
    for year, ratios in sorted(a.ratios.items(), reverse=True):
        out.extend((f"<h3>FY {_text(year)}</h3>", _table(("Ratio", "Result", "Formula"), [
            (r.label, _ratio(r, currency_by_year.get(year, "")), r.formula) for r in ratios.values()
        ])))
    if not any(a.ratios.values()):
        out.append(_paragraph("n/a — no financial ratios were supplied."))
    out.append("</section><section><h2>Credit risk alerts</h2>")
    out.append(_list([
        f"FY {alert.fiscal_year} · {alert.severity.value.title()} · {alert.title} · "
                f"{alert.interpretation} · Threshold: {alert.threshold} · "
        f"Measured value: {alert.measured_value if alert.measured_value is not None else 'n/a'} · "
        f"Source: {alert.source_reference or 'n/a'}"
        for alert in a.alerts
    ], "No screening alerts were triggered by the configured rules."))
    out.extend(("</section><section><h2>Credit commentary</h2>", _paragraph(f"Generated by: {c.generated_by}")))
    for name in ("executive_summary", "liquidity", "leverage", "profitability", "cash_flow",
                 "key_risks", "positive_indicators", "overall_assessment", "missing_information", "notes"):
        val = getattr(c, name)
        out.extend((f"<h3>{name.replace('_', ' ').capitalize()}</h3>",
                    _list(val, "None identified from available information.") if isinstance(val, list) else _paragraph(val)))
    out.append("</section><section><h2>Data quality and sources</h2>")
    for p in f.periods:
        missing = p.missing_fields()
        complete = (len(ALL_FIELDS) - len(missing)) / len(ALL_FIELDS)
        out.append(_paragraph(f"FY {p.fiscal_year}: {complete:.0%} of statement fields present."))
        if missing:
            out.append(_paragraph("Missing: " + ", ".join(FIELD_LABELS[field] for field in missing)))
    out.append(_list(f.warnings + [i.message for i in a.validation_issues], "No data warnings supplied."))
    out.append(_list(c.sources, "No sources supplied."))
    out.append("</section><section><h2>Methodology and limitations</h2>")
    out.append(_paragraph("Ratios and screening scores are taken from the deterministic analysis engine. "
                          "The report uses confirmed inputs and preserves unavailable values."))
    if methodology_text():
        out.append(_paragraph("For the full scoring methodology, ratio definitions, thresholds and assumptions, see the Methodology page in SolvIQ."))
    else:
        out.append(_paragraph("The scoring methodology document has not been supplied in this build."))
    out.extend((_paragraph(config.SCORE_DISCLAIMER), "</section></body></html>"))
    return "\n".join(out)
