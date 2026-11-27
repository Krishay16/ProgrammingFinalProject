"""Deterministic first-pass commentary on confirmed financial results."""
from typing import Literal

from pydantic import BaseModel

from src.models import ALL_FIELDS, FIELD_LABELS, AnalysisResult, RatioStatus

ASSESSMENT = (
    "This is a preliminary screening; liquidity, debt maturity and cash-flow resilience "
    "should be examined by a credit professional before any lending decision."
)


class CreditCommentary(BaseModel):
    executive_summary: str
    liquidity: str
    leverage: str
    profitability: str
    cash_flow: str
    key_risks: list[str]
    positive_indicators: list[str]
    overall_assessment: str
    missing_information: list[str]
    sources: list[str]
    generated_by: Literal["template", "llm"]
    notes: list[str]


def template_commentary(a: AnalysisResult) -> CreditCommentary:
    """Describe engine results and explicitly identify unavailable evidence."""
    f = a.financials
    latest = f.latest()
    ratios = a.ratios.get(latest.fiscal_year, {}) if latest else {}
    currency = latest.currency if latest else ""
    missing = []
    positives = []

    def observation(key, label, unit, interpret):
        ratio = ratios.get(key)
        if ratio is None or ratio.status != RatioStatus.VALID or ratio.value is None:
            reason = ratio.explanation if ratio and ratio.explanation else "No usable result was supplied."
            missing.append(f"{label} — {reason}")
            return f"{label} is unavailable. {reason}"
        value = ratio.value
        display = {"%": f"{value:.1%}", "x": f"{value:.2f}x",
                   "currency": f"{currency} {value / 1e6:,.2f}m"}[unit]
        return (
            f"Observation: {label} was {display} in FY {latest.fiscal_year}. "
            f"Interpretation: {interpret(value)}"
        )

    liquidity = observation(
        "current_ratio", "Current ratio", "x",
        lambda v: ("Current assets are below current liabilities, indicating limited "
                   "balance-sheet coverage of short-term obligations." if v < 1 else
                   "Current assets provide some balance-sheet coverage of current liabilities."
                   if v < 1.5 else "Current assets provide a stronger short-term balance-sheet buffer."),
    )
    leverage = observation(
        "net_debt_to_ebitda", "Net debt to EBITDA", "x",
        lambda _: "The ratio compares net borrowings with earnings and should be read alongside debt maturities.",
    )
    net_debt = ratios.get("net_debt")
    if net_debt and net_debt.status == RatioStatus.VALID and net_debt.value is not None and net_debt.value < 0:
        leverage += " Interpretation: the confirmed inputs indicate a net cash position."
    coverage = observation(
        "interest_coverage", "Interest coverage", "x",
        lambda v: "Operating earnings may offer limited interest coverage." if v < 2 else
        "Operating earnings cover reported interest expense on this measure.",
    )
    profitability = observation(
        "operating_margin", "Operating margin", "%",
        lambda v: "Operating costs exceeded revenue." if v < 0 else
        "Reported operations were profitable." if v > 0 else "Operations broke even on this measure.",
    )
    growth = observation(
        "revenue_growth", "Revenue growth", "%",
        lambda v: "Revenue fell across comparable periods." if v < 0 else
        "Revenue increased across comparable periods." if v > 0 else "Revenue was flat.",
    )
    cash_flow = observation(
        "free_cash_flow", "Free cash flow", "currency",
        lambda v: "Operating cash flow did not cover capital expenditure." if v < 0 else
        "Operating cash flow exceeded capital expenditure." if v > 0 else
        "Operating cash flow matched capital expenditure.",
    )
    for key, threshold, text in (
        ("current_ratio", 1.0, "Current assets exceed current liabilities."),
        ("operating_margin", 0.0, "Operating margin was positive."),
        ("free_cash_flow", 0.0, "Free cash flow was positive."),
    ):
        ratio = ratios.get(key)
        if ratio and ratio.status == RatioStatus.VALID and ratio.value is not None and ratio.value > threshold:
            positives.append(text)

    if latest:
        missing.extend(FIELD_LABELS[field] for field in latest.missing_fields())
    else:
        missing.append("Confirmed annual financial statements.")
    source_label = f.source_type.value.replace("_", " ").upper()
    sources = {source_label}
    for period in f.periods:
        if period.period_end or period.filing_date:
            details = [f"FY {period.fiscal_year}"]
            if period.period_end:
                details.append(f"period ended {period.period_end}")
            if period.filing_date:
                details.append(f"filed {period.filing_date}")
            sources.add(" · ".join(details))
        for field in ALL_FIELDS:
            p = getattr(period, field).provenance
            if p and p.source_ref:
                sources.add(" · ".join(filter(None, (p.source_ref, p.location,
                            f"filed {p.filing_date}" if p.filing_date else None))))

    score = a.score
    summary = (
        f"The engine returned {score.total:g}/100"
        + (f" ({score.category})." if score.category else ".")
        if score.total is not None else "The engine did not return a full screening score."
    )
    risks = [f"{alert.title} — {alert.interpretation}" for alert in a.alerts]
    return CreditCommentary(
        executive_summary=summary,
        liquidity=liquidity,
        leverage=f"{leverage} {coverage}",
        profitability=f"{profitability} {growth}",
        cash_flow=cash_flow,
        key_risks=risks,
        positive_indicators=positives,
        overall_assessment=ASSESSMENT,
        missing_information=list(dict.fromkeys(missing)),
        sources=sorted(sources),
        generated_by="template",
        notes=["Commentary is generated locally from the confirmed data and engine results."],
    )


def generate_commentary(a: AnalysisResult, allow_external_llm: bool) -> CreditCommentary:
    """Use the local template. This release has no external provider integration."""
    return template_commentary(a)
