"""Rule-based screening alerts for SolvIQ. Owned by Person 4.

Alerts flag ratios that cross a configured SCREENING threshold for the latest fiscal year,
plus a revenue trend alert across years and a data-quality alert. An alert is a prompt for
the analyst to look closer; it is never evidence of default or financial distress.

All thresholds live in ALERT_CONFIG (illustrative design assumptions for this MVP, not
validated banking standards; sensible thresholds differ by industry).
Trigger comparisons are strict: a value exactly on the trigger does NOT fire.
"""
from __future__ import annotations

from typing import Optional

from src.credit_scoring import fmt_value
from src.financial_calculations import ebitda_value
from src.models import (FIELD_LABELS, CompanyFinancials, FinancialPeriod, RatioResult,
                        RatioStatus, RiskAlert, Severity)

# --------------------------------------------------------------------------------------
# ALERT_CONFIG
#   "lower is worse" alerts (fire when value < trigger_below):
#       high if value < high_below; medium if value < medium_below; else low
#   "higher is worse" alerts (fire when value > trigger_above):
#       high if value > high_above; medium if value > medium_above; else low
#   Percentages are decimals (0.05 = 5%).
# --------------------------------------------------------------------------------------
ALERT_CONFIG: dict = {
    # current_ratio < 1.0x. low 0.9 to <1.0, medium 0.75 to <0.9, high < 0.75
    "liquidity": {"trigger_below": 1.0, "medium_below": 0.9, "high_below": 0.75},
    # debt_to_equity > 2.0x. low <= 3.0, medium <= 4.0, high > 4.0
    "debt_to_equity": {"trigger_above": 2.0, "medium_above": 3.0, "high_above": 4.0},
    # net_debt_to_ebitda > 3.0x. low <= 4.0, medium <= 5.0, high > 5.0
    "net_debt_to_ebitda": {"trigger_above": 3.0, "medium_above": 4.0, "high_above": 5.0},
    # total_equity <= 0 always fires with this severity
    "non_positive_equity": {"severity": "high"},
    # interest_coverage < 2.0x. low 1.5 to <2.0, medium 1.0 to <1.5, high < 1.0
    "coverage": {"trigger_below": 2.0, "medium_below": 1.5, "high_below": 1.0},
    # operating_margin < 0%. low >= -5%, medium >= -15%, high < -15%
    "profitability": {"trigger_below": 0.0, "medium_below": -0.05, "high_below": -0.15},
    # free_cash_flow < 0. Severity from fcf_margin: low >= -5%, medium >= -10%,
    # high < -10%; "medium" when the FCF margin cannot be calculated.
    "cash_flow": {"trigger_below": 0.0, "medium_below": -0.05, "high_below": -0.10,
                  "severity_without_margin": "medium"},
    # revenue_growth < 0 in the latest AND the prior year. Severity from the cumulative
    # two-year decline (1 - revenue_latest / revenue_two_years_earlier):
    # low < 5%, medium 5% to < 15%, high >= 15%
    "trend": {"medium_at_or_above": 0.05, "high_at_or_above": 0.15},
    # any key input missing in the latest year. low 1, medium 2-3, high >= 4 missing
    "data_quality": {
        "medium_at_or_above": 2, "high_at_or_above": 4,
        # inputs needed by the scored ratios; "ebitda" counts as missing only when it
        # cannot be derived as EBIT + D&A
        "key_inputs": ["current_assets", "current_liabilities", "cash", "short_term_debt",
                       "long_term_debt", "total_equity", "revenue", "ebit", "ebitda",
                       "interest_expense", "operating_cash_flow", "capex"],
    },
}

# Exact interpretation texts (agreed with the team; do not paraphrase).
LIQUIDITY_TEXT = ("Current assets are below current liabilities, indicating a potentially weak "
                  "short-term liquidity position.")
LEVERAGE_TEXT = "Financial leverage exceeds the configured screening threshold."
COVERAGE_TEXT = ("The company's operating earnings may provide limited coverage for interest "
                 "expense.")
PROFITABILITY_TEXT = "The company reported a negative operating margin."
CASH_FLOW_TEXT = ("The company generated negative free cash flow during the reporting "
                  "period.")
TREND_TEXT = "Revenue has declined over consecutive comparable reporting periods."

_DEBT = ["short_term_debt", "long_term_debt"]


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def severity_lower_is_worse(value: float, rule: dict) -> Severity:
    """Severity for alerts that fire when a value is too LOW."""
    if value < rule["high_below"]:
        return Severity.HIGH
    if value < rule["medium_below"]:
        return Severity.MEDIUM
    return Severity.LOW


def severity_higher_is_worse(value: float, rule: dict) -> Severity:
    """Severity for alerts that fire when a value is too HIGH."""
    if value > rule["high_above"]:
        return Severity.HIGH
    if value > rule["medium_above"]:
        return Severity.MEDIUM
    return Severity.LOW


def _count_severity(amount: float, rule: dict) -> Severity:
    if amount >= rule["high_at_or_above"]:
        return Severity.HIGH
    if amount >= rule["medium_at_or_above"]:
        return Severity.MEDIUM
    return Severity.LOW


def source_reference(periods: list[FinancialPeriod], fields: list[str]) -> Optional[str]:
    """Where the inputs came from: 'tag | location | source_ref' per distinct provenance.

    Joined with '; '. None when no input has provenance.
    """
    refs: list[str] = []
    for p in periods:
        for field in fields:
            prov = getattr(p, field).provenance
            if prov is None:
                continue
            ref = " | ".join(x for x in (prov.tag, prov.location, prov.source_ref) if x)
            if ref and ref not in refs:
                refs.append(ref)
    return "; ".join(refs) or None


def _valid(r: Optional[RatioResult]) -> bool:
    return r is not None and r.status == RatioStatus.VALID


def _pct(threshold: float) -> str:
    return f"{threshold * 100:g}%"


def _ebitda_fields(p: FinancialPeriod) -> list[str]:
    """Fields EBITDA came from (reported, or EBIT + D&A when derived)."""
    return ["ebitda"] if p.get("ebitda") is not None else ["ebit", "depreciation_amortization"]


# --------------------------------------------------------------------------------------
# Individual rules (each returns a list so "no alert" is simply [])
# --------------------------------------------------------------------------------------
def _liquidity(r: dict[str, RatioResult], p: FinancialPeriod) -> list[RiskAlert]:
    cr, rule = r.get("current_ratio"), ALERT_CONFIG["liquidity"]
    if not _valid(cr) or not cr.value < rule["trigger_below"]:
        return []
    return [RiskAlert(
        alert_type="liquidity", title="Current ratio below 1.0x",
        severity=severity_lower_is_worse(cr.value, rule), indicator="current_ratio",
        measured_value=cr.value, threshold=f"< {rule['trigger_below']:.1f}x",
        interpretation=LIQUIDITY_TEXT, fiscal_year=p.fiscal_year,
        source_reference=source_reference([p], ["current_assets", "current_liabilities"]))]


def _leverage(r: dict[str, RatioResult], p: FinancialPeriod) -> list[RiskAlert]:
    alerts: list[RiskAlert] = []
    equity = p.get("total_equity")
    if equity is not None and equity <= 0:
        kind = "Negative" if equity < 0 else "Zero"
        alerts.append(RiskAlert(
            alert_type="leverage", title=f"{kind} shareholders' equity",
            severity=Severity(ALERT_CONFIG["non_positive_equity"]["severity"]),
            indicator="total_equity", measured_value=equity,
            threshold="<= 0 (zero or negative equity)", interpretation=LEVERAGE_TEXT,
            fiscal_year=p.fiscal_year, source_reference=source_reference([p], ["total_equity"])))

    checks = [("debt_to_equity", "Debt to equity above screening threshold",
               [*_DEBT, "total_equity"]),
              ("net_debt_to_ebitda", "Net debt / EBITDA above screening threshold",
               [*_DEBT, "cash", *_ebitda_fields(p)])]
    for key, title, fields in checks:
        ratio, rule = r.get(key), ALERT_CONFIG[key]
        if not _valid(ratio) or not ratio.value > rule["trigger_above"]:
            continue
        alerts.append(RiskAlert(
            alert_type="leverage", title=title,
            severity=severity_higher_is_worse(ratio.value, rule), indicator=key,
            measured_value=ratio.value, threshold=f"> {rule['trigger_above']:.1f}x",
            interpretation=LEVERAGE_TEXT, fiscal_year=p.fiscal_year,
            source_reference=source_reference([p], fields)))
    return alerts


def _coverage(r: dict[str, RatioResult], p: FinancialPeriod) -> list[RiskAlert]:
    ic, rule = r.get("interest_coverage"), ALERT_CONFIG["coverage"]
    if not _valid(ic) or not ic.value < rule["trigger_below"]:
        return []
    return [RiskAlert(
        alert_type="coverage", title="Interest coverage below 2.0x",
        severity=severity_lower_is_worse(ic.value, rule), indicator="interest_coverage",
        measured_value=ic.value, threshold=f"< {rule['trigger_below']:.1f}x",
        interpretation=COVERAGE_TEXT, fiscal_year=p.fiscal_year,
        source_reference=source_reference([p], ["ebit", "interest_expense"]))]


def _profitability(r: dict[str, RatioResult], p: FinancialPeriod) -> list[RiskAlert]:
    om, rule = r.get("operating_margin"), ALERT_CONFIG["profitability"]
    if not _valid(om) or not om.value < rule["trigger_below"]:
        return []
    return [RiskAlert(
        alert_type="profitability", title="Negative operating margin",
        severity=severity_lower_is_worse(om.value, rule), indicator="operating_margin",
        measured_value=om.value, threshold=f"< {_pct(rule['trigger_below'])}",
        interpretation=PROFITABILITY_TEXT, fiscal_year=p.fiscal_year,
        source_reference=source_reference([p], ["ebit", "revenue"]))]


def _cash_flow(r: dict[str, RatioResult], p: FinancialPeriod) -> list[RiskAlert]:
    fcf, rule = r.get("free_cash_flow"), ALERT_CONFIG["cash_flow"]
    if not _valid(fcf) or not fcf.value < rule["trigger_below"]:
        return []
    margin = r.get("fcf_margin")
    fields = ["operating_cash_flow", "capex"]
    if _valid(margin):
        severity = severity_lower_is_worse(margin.value, rule)
        fields.append("revenue")
        basis = f" (FCF margin {fmt_value(margin.value, '%')})"
    else:
        severity = Severity(rule["severity_without_margin"])
        basis = " (FCF margin unavailable)"
    return [RiskAlert(
        alert_type="cash_flow", title="Negative free cash flow", severity=severity,
        indicator="free_cash_flow", measured_value=fcf.value,
        threshold=f"< 0{basis}", interpretation=CASH_FLOW_TEXT, fiscal_year=p.fiscal_year,
        source_reference=source_reference([p], fields))]


def _trend(ratios: dict[int, dict[str, RatioResult]], f: CompanyFinancials,
           p: FinancialPeriod) -> list[RiskAlert]:
    """Revenue fell in each of the last two comparable (consecutive annual) periods."""
    latest = ratios.get(p.fiscal_year, {}).get("revenue_growth")
    prior = ratios.get(p.fiscal_year - 1, {}).get("revenue_growth")
    if not (_valid(latest) and _valid(prior) and latest.value < 0 and prior.value < 0):
        return []
    # Cumulative decline from two years earlier: 1 - revenue_latest / revenue_two_years_ago
    decline = 1 - latest.inputs["revenue"] / prior.inputs["prior_revenue"]
    periods = [x for x in (p, f.period(p.fiscal_year - 1), f.period(p.fiscal_year - 2))
               if x is not None]
    return [RiskAlert(
        alert_type="trend", title="Consecutive revenue decline",
        severity=_count_severity(decline, ALERT_CONFIG["trend"]), indicator="revenue_growth",
        measured_value=latest.value,
        threshold=(f"revenue growth < 0% in FY{p.fiscal_year - 1} and FY{p.fiscal_year} "
                   f"(cumulative decline {decline:.1%})"),
        interpretation=TREND_TEXT, fiscal_year=p.fiscal_year,
        source_reference=source_reference(periods, ["revenue"]))]


def missing_key_inputs(p: FinancialPeriod) -> list[str]:
    """Key inputs missing in a period ('ebitda' only if it cannot be derived)."""
    missing = []
    for field in ALERT_CONFIG["data_quality"]["key_inputs"]:
        if field == "ebitda":
            if ebitda_value(p)[0] is None:
                missing.append(field)
        elif p.get(field) is None:
            missing.append(field)
    return missing


def _data_quality(p: FinancialPeriod) -> list[RiskAlert]:
    missing = missing_key_inputs(p)
    if not missing:
        return []
    key_inputs = ALERT_CONFIG["data_quality"]["key_inputs"]
    present = [x for x in key_inputs if x not in missing and x != "ebitda"]
    labels = ", ".join(FIELD_LABELS[x] for x in missing)
    return [RiskAlert(
        alert_type="data_quality", title="Key inputs missing",
        severity=_count_severity(len(missing), ALERT_CONFIG["data_quality"]),
        indicator="key_inputs", measured_value=float(len(missing)),
        threshold=f"any of the {len(key_inputs)} key inputs missing",
        interpretation=(f"{len(missing)} key input(s) are missing for FY{p.fiscal_year}: "
                        f"{labels}. Ratios and score factors that need them cannot be "
                        "calculated; missing values are never treated as zero."),
        fiscal_year=p.fiscal_year, source_reference=source_reference([p], present))]


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------
def generate_alerts(ratios: dict[int, dict[str, RatioResult]],
                    f: CompanyFinancials) -> list[RiskAlert]:
    """Screening alerts for the latest fiscal year plus the revenue trend alert.

    Financial institutions only get the data-quality alert: industrial-company ratio
    thresholds would be misleading for banks and insurers.
    """
    p = f.latest()
    if p is None:
        return []
    alerts: list[RiskAlert] = []
    if not f.company.is_financial_institution:
        r = ratios.get(p.fiscal_year, {})
        alerts += _liquidity(r, p)
        alerts += _leverage(r, p)
        alerts += _coverage(r, p)
        alerts += _profitability(r, p)
        alerts += _cash_flow(r, p)
        alerts += _trend(ratios, f, p)
    alerts += _data_quality(p)
    return alerts
