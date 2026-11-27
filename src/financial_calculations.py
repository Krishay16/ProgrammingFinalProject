"""Deterministic financial ratio calculations for SolvIQ. Owned by Person 4.

One function per standard ratio key, each with the signature
    <ratio_key>(p: FinancialPeriod, prev: FinancialPeriod | None = None) -> RatioResult

Conventions (from the shared contract):
- All money inputs are in FULL currency units. A missing value is None, never 0.
- Percentage ratios are stored as decimals (0.25 means 25%). Values are never rounded here;
  rounding is the UI's job.
- Missing inputs -> status UNAVAILABLE. Inputs present but the ratio is not meaningful
  (zero or negative denominator, inconsistent sign, ...) -> status UNDEFINED.
- Every case is handled with explicit None / sign checks. There is deliberately NO
  catch-all try/except: a coding bug must make the tests fail, not hide as UNDEFINED.
"""
from __future__ import annotations

from typing import Callable, Optional

from src.models import (FIELD_LABELS, CompanyFinancials, FinancialPeriod, RatioResult,
                        RatioStatus)

DivisionResult = tuple[Optional[float], RatioStatus, str]
RatioFunction = Callable[[FinancialPeriod, Optional[FinancialPeriod]], RatioResult]

# key -> (label, category, unit, human-readable formula)
RATIO_META: dict[str, tuple[str, str, str, str]] = {
    "current_ratio": ("Current Ratio", "liquidity", "x",
                      "Current Assets / Current Liabilities"),
    "cash_ratio": ("Cash Ratio", "liquidity", "x",
                   "Cash and Cash Equivalents / Current Liabilities"),
    "working_capital": ("Working Capital", "liquidity", "currency",
                        "Current Assets - Current Liabilities"),
    "total_debt": ("Total Debt", "leverage", "currency",
                   "Short-term Debt + Long-term Debt"),
    "debt_to_equity": ("Debt to Equity", "leverage", "x",
                       "Total Debt / Total Shareholders' Equity"),
    "debt_to_assets": ("Debt to Assets", "leverage", "%",
                       "Total Debt / Total Assets"),
    "net_debt": ("Net Debt", "leverage", "currency",
                 "Total Debt - Cash and Cash Equivalents"),
    "net_debt_to_ebitda": ("Net Debt / EBITDA", "leverage", "x",
                           "(Total Debt - Cash) / EBITDA"),
    "operating_margin": ("Operating Margin", "profitability", "%",
                         "Operating Income (EBIT) / Revenue"),
    "net_profit_margin": ("Net Profit Margin", "profitability", "%",
                          "Net Income / Revenue"),
    "return_on_assets": ("Return on Assets", "profitability", "%",
                         "Net Income / Total Assets (end of period)"),
    "interest_coverage": ("Interest Coverage", "coverage", "x",
                          "Operating Income (EBIT) / Interest Expense"),
    "free_cash_flow": ("Free Cash Flow", "cash_flow", "currency",
                       "Operating Cash Flow - Capital Expenditures"),
    "fcf_margin": ("FCF Margin", "cash_flow", "%",
                   "(Operating Cash Flow - Capital Expenditures) / Revenue"),
    "revenue_growth": ("Revenue Growth", "growth", "%",
                       "Revenue / Prior-year Revenue - 1"),
}

# Labels for inputs that are not model fields.
_EXTRA_LABELS: dict[str, str] = {"prior_revenue": "Prior-year revenue"}
_DEBT_FIELDS = ("short_term_debt", "long_term_debt")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _label(field: str) -> str:
    """Human-readable name of an input field."""
    return FIELD_LABELS.get(field) or _EXTRA_LABELS.get(field, field)


def safe_divide(numerator: Optional[float], denominator: Optional[float],
                require_positive_denominator: bool = False, *,
                numerator_name: str = "Numerator", denominator_name: str = "Denominator",
                negative_reason: Optional[str] = None) -> DivisionResult:
    """Divide two possibly-missing numbers without ever raising.

    Returns (value, status, reason):
    - any input None            -> (None, UNAVAILABLE, "<name> is missing.")
    - denominator == 0          -> (None, UNDEFINED, "denominator is zero ...")
    - denominator < 0 and require_positive_denominator
                                -> (None, UNDEFINED, negative_reason or a default reason)
    - otherwise                 -> (numerator / denominator, VALID, "")
    A negative NUMERATOR is always allowed (e.g. a loss gives a negative margin).
    """
    missing = [name for name, v in ((numerator_name, numerator),
                                    (denominator_name, denominator)) if v is None]
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        return None, RatioStatus.UNAVAILABLE, f"{' and '.join(missing)} {verb} missing."
    if denominator == 0:
        return (None, RatioStatus.UNDEFINED,
                f"denominator is zero ({denominator_name} = 0), so the ratio is undefined.")
    if require_positive_denominator and denominator < 0:
        reason = negative_reason or (f"{denominator_name} is negative: the ratio is not "
                                     "meaningful with a negative denominator.")
        return None, RatioStatus.UNDEFINED, reason
    return numerator / denominator, RatioStatus.VALID, ""


def total_debt_value(p: FinancialPeriod) -> Optional[float]:
    """Short-term debt + long-term debt, or None unless BOTH components are known.

    An analyst can enter 0 for a component known to be zero; a missing component is never
    treated as 0.
    """
    std, ltd = p.get("short_term_debt"), p.get("long_term_debt")
    if std is None or ltd is None:
        return None
    return std + ltd


def ebitda_value(p: FinancialPeriod) -> tuple[Optional[float], str]:
    """EBITDA to use for a period, with a note saying where it came from.

    - reported EBITDA if present                        -> (ebitda, "")
    - else EBIT + D&A if both are known                 -> (sum, note saying it is DERIVED)
    - else                                              -> (None, note saying why missing)
    """
    reported = p.get("ebitda")
    if reported is not None:
        return reported, ""
    ebit, da = p.get("ebit"), p.get("depreciation_amortization")
    if ebit is not None and da is not None:
        return ebit + da, ("EBITDA was not reported; it is derived as EBIT + depreciation "
                           "and amortization.")
    return None, ("EBITDA is missing and cannot be derived (needs both EBIT and "
                  "depreciation and amortization).")


def _get(p: FinancialPeriod, *fields: str) -> dict[str, Optional[float]]:
    """Raw input values for the given model fields (None when missing)."""
    return {f: p.get(f) for f in fields}


def _missing_reason(inputs: dict[str, Optional[float]],
                    fields: Optional[list[str]] = None) -> Optional[str]:
    """Explanation listing the missing inputs, or None if nothing is missing."""
    fields = fields if fields is not None else list(inputs)
    missing = [f for f in fields if inputs.get(f) is None]
    if not missing:
        return None
    verb = "is" if len(missing) == 1 else "are"
    text = f"{', '.join(_label(f) for f in missing)} {verb} missing."
    if any(f in _DEBT_FIELDS for f in missing):
        text += (" Total debt needs both short-term and long-term debt (enter 0 if a "
                 "component is known to be zero).")
    return text


def _result(key: str, p: FinancialPeriod, value: Optional[float], status: RatioStatus,
            inputs: dict[str, Optional[float]], explanation: str = "") -> RatioResult:
    """Build a RatioResult with the metadata registered for `key`."""
    label, category, unit, formula = RATIO_META[key]
    return RatioResult(key=key, label=label, category=category, fiscal_year=p.fiscal_year,
                       value=value if status == RatioStatus.VALID else None, status=status,
                       unit=unit, formula=formula, inputs=inputs, explanation=explanation)


def _join(*parts: str) -> str:
    """Join non-empty explanation fragments with a space."""
    return " ".join(part for part in parts if part)


def _simple_ratio(key: str, p: FinancialPeriod, num_field: str, den_field: str,
                  negative_reason: str, note: str = "") -> RatioResult:
    """Ratio of two model fields with a strictly positive denominator."""
    inputs = _get(p, num_field, den_field)
    value, status, reason = safe_divide(
        inputs[num_field], inputs[den_field], require_positive_denominator=True,
        numerator_name=_label(num_field), denominator_name=_label(den_field),
        negative_reason=negative_reason)
    return _result(key, p, value, status, inputs, _join(reason, note))


# --------------------------------------------------------------------------------------
# Liquidity
# --------------------------------------------------------------------------------------
def current_ratio(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Current Ratio = current_assets / current_liabilities. Unit: x. Category: liquidity.

    Edge cases: either input missing -> UNAVAILABLE; current liabilities zero or negative
    -> UNDEFINED (a negative denominator would flip the sign and mislead).
    """
    return _simple_ratio("current_ratio", p, "current_assets", "current_liabilities",
                         "Current liabilities are negative: ratio not meaningful.")


def cash_ratio(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Cash Ratio = cash / current_liabilities. Unit: x. Category: liquidity.

    Edge cases: either input missing -> UNAVAILABLE; current liabilities zero or negative
    -> UNDEFINED.
    """
    return _simple_ratio("cash_ratio", p, "cash", "current_liabilities",
                         "Current liabilities are negative: ratio not meaningful.")


def working_capital(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Working Capital = current_assets - current_liabilities. Unit: currency. Liquidity.

    No denominator. Edge cases: either input missing -> UNAVAILABLE. A negative result is
    VALID (current liabilities exceed current assets) and is explained.
    """
    inputs = _get(p, "current_assets", "current_liabilities")
    reason = _missing_reason(inputs)
    if reason:
        return _result("working_capital", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    value = inputs["current_assets"] - inputs["current_liabilities"]
    note = ("Negative working capital: current liabilities exceed current assets."
            if value < 0 else "")
    return _result("working_capital", p, value, RatioStatus.VALID, inputs, note)


# --------------------------------------------------------------------------------------
# Leverage
# --------------------------------------------------------------------------------------
def total_debt(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Total Debt = short_term_debt + long_term_debt. Unit: currency. Category: leverage.

    No denominator. Edge cases: if EITHER component is missing -> UNAVAILABLE (a missing
    component is never assumed to be 0; the analyst can type 0 if they know it is zero).
    """
    inputs = _get(p, *_DEBT_FIELDS)
    reason = _missing_reason(inputs)
    if reason:
        return _result("total_debt", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    return _result("total_debt", p, total_debt_value(p), RatioStatus.VALID, inputs)


def debt_to_equity(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Debt to Equity = total_debt / total_equity. Unit: x. Category: leverage.

    Numerator: short_term_debt + long_term_debt (both required).
    Edge cases: any input missing -> UNAVAILABLE; equity zero -> UNDEFINED; equity negative
    -> UNDEFINED ("negative equity: ratio not meaningful").
    """
    inputs = _get(p, *_DEBT_FIELDS, "total_equity")
    reason = _missing_reason(inputs)
    if reason:
        return _result("debt_to_equity", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    value, status, why = safe_divide(
        total_debt_value(p), inputs["total_equity"], require_positive_denominator=True,
        numerator_name="Total debt", denominator_name=_label("total_equity"),
        negative_reason="negative equity: ratio not meaningful.")
    return _result("debt_to_equity", p, value, status, inputs, why)


def debt_to_assets(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Debt to Assets = total_debt / total_assets. Unit: % (decimal). Category: leverage.

    Edge cases: any input missing -> UNAVAILABLE; total assets zero or negative -> UNDEFINED.
    """
    inputs = _get(p, *_DEBT_FIELDS, "total_assets")
    reason = _missing_reason(inputs)
    if reason:
        return _result("debt_to_assets", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    value, status, why = safe_divide(
        total_debt_value(p), inputs["total_assets"], require_positive_denominator=True,
        numerator_name="Total debt", denominator_name=_label("total_assets"),
        negative_reason="Total assets are negative: ratio not meaningful.")
    return _result("debt_to_assets", p, value, status, inputs, why)


def net_debt(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Net Debt = total_debt - cash. Unit: currency. Category: leverage.

    No denominator. Edge cases: any input missing -> UNAVAILABLE. A negative result is VALID
    and means a net cash position (cash exceeds total debt).
    """
    inputs = _get(p, *_DEBT_FIELDS, "cash")
    reason = _missing_reason(inputs)
    if reason:
        return _result("net_debt", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    value = total_debt_value(p) - inputs["cash"]
    note = "Net cash position: cash exceeds total debt." if value < 0 else ""
    return _result("net_debt", p, value, RatioStatus.VALID, inputs, note)


def net_debt_to_ebitda(p: FinancialPeriod,
                       prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Net Debt / EBITDA = (total_debt - cash) / EBITDA. Unit: x. Category: leverage.

    EBITDA: reported value, else EBIT + D&A (explanation says it is derived).
    Edge cases: any input missing / EBITDA not derivable -> UNAVAILABLE; EBITDA zero or
    negative -> UNDEFINED. A negative result (negative net debt = net cash) is VALID and
    explained, because it does not mean high leverage.
    """
    inputs = _get(p, *_DEBT_FIELDS, "cash", "ebitda")
    ebitda, ebitda_note = ebitda_value(p)
    if inputs["ebitda"] is None:  # show what the derivation used (or would have used)
        inputs.update(_get(p, "ebit", "depreciation_amortization"))
    reason = _missing_reason(inputs, [*_DEBT_FIELDS, "cash"])
    if reason or ebitda is None:
        explanation = _join(reason or "", ebitda_note if ebitda is None else "")
        return _result("net_debt_to_ebitda", p, None, RatioStatus.UNAVAILABLE, inputs,
                       explanation)
    nd = total_debt_value(p) - inputs["cash"]
    value, status, why = safe_divide(
        nd, ebitda, require_positive_denominator=True,
        numerator_name="Net debt", denominator_name="EBITDA",
        negative_reason="EBITDA is negative: ratio not meaningful.")
    net_cash_note = ""
    if status == RatioStatus.VALID and nd < 0:
        net_cash_note = ("Negative net debt means a net cash position (cash exceeds total "
                         "debt); a negative value here is not a sign of high leverage.")
    return _result("net_debt_to_ebitda", p, value, status, inputs,
                   _join(why, ebitda_note, net_cash_note))


# --------------------------------------------------------------------------------------
# Profitability
# --------------------------------------------------------------------------------------
def operating_margin(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Operating Margin = ebit / revenue. Unit: % (decimal). Category: profitability.

    Edge cases: either input missing -> UNAVAILABLE; revenue zero or negative -> UNDEFINED.
    Negative EBIT is VALID (an operating loss gives a negative margin).
    """
    return _simple_ratio("operating_margin", p, "ebit", "revenue",
                         "Revenue is negative: margin not meaningful.")


def net_profit_margin(p: FinancialPeriod,
                      prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Net Profit Margin = net_income / revenue. Unit: % (decimal). Profitability.

    Edge cases: either input missing -> UNAVAILABLE; revenue zero or negative -> UNDEFINED.
    A net loss is VALID and gives a negative margin.
    """
    return _simple_ratio("net_profit_margin", p, "net_income", "revenue",
                         "Revenue is negative: margin not meaningful.")


def return_on_assets(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Return on Assets = net_income / total_assets. Unit: % (decimal). Profitability.

    Uses END-OF-PERIOD total assets (not the average of opening and closing assets).
    Edge cases: either input missing -> UNAVAILABLE; total assets zero or negative ->
    UNDEFINED. A net loss is VALID and gives a negative return.
    """
    return _simple_ratio("return_on_assets", p, "net_income", "total_assets",
                         "Total assets are negative: ratio not meaningful.",
                         note="Uses end-of-period total assets, not average assets.")


# --------------------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------------------
def interest_coverage(p: FinancialPeriod,
                      prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Interest Coverage = ebit / interest_expense. Unit: x. Category: coverage.

    interest_expense is stored as a POSITIVE amount.
    Edge cases: either input missing -> UNAVAILABLE; interest expense zero -> UNDEFINED
    ("no interest expense reported; coverage not meaningful"); interest expense negative ->
    UNDEFINED ("inconsistent sign"). Negative EBIT is VALID (coverage below zero).
    """
    inputs = _get(p, "ebit", "interest_expense")
    reason = _missing_reason(inputs)
    if reason:
        return _result("interest_coverage", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    ebit, interest = inputs["ebit"], inputs["interest_expense"]
    if interest == 0:
        return _result("interest_coverage", p, None, RatioStatus.UNDEFINED, inputs,
                       "no interest expense reported; coverage not meaningful.")
    if interest < 0:
        return _result("interest_coverage", p, None, RatioStatus.UNDEFINED, inputs,
                       "inconsistent sign: interest expense is negative, but it must be "
                       "stored as a positive amount; coverage not meaningful.")
    note = ("Negative EBIT: operating income does not cover interest expense."
            if ebit < 0 else "")
    return _result("interest_coverage", p, ebit / interest, RatioStatus.VALID, inputs, note)


# --------------------------------------------------------------------------------------
# Cash flow
# --------------------------------------------------------------------------------------
_CAPEX_SIGN_REASON = ("inconsistent sign: capital expenditures are negative, but they must "
                      "be stored as a positive amount (size of the outflow).")


def free_cash_flow(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Free Cash Flow = operating_cash_flow - capex. Unit: currency. Category: cash_flow.

    capex is stored as a POSITIVE amount. No denominator.
    Edge cases: either input missing -> UNAVAILABLE; capex negative -> UNDEFINED
    (inconsistent sign: subtracting it would wrongly ADD cash). A negative FCF is VALID.
    """
    inputs = _get(p, "operating_cash_flow", "capex")
    reason = _missing_reason(inputs)
    if reason:
        return _result("free_cash_flow", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    if inputs["capex"] < 0:
        return _result("free_cash_flow", p, None, RatioStatus.UNDEFINED, inputs,
                       _CAPEX_SIGN_REASON)
    value = inputs["operating_cash_flow"] - inputs["capex"]
    note = ("Negative free cash flow: operating cash flow does not cover capital "
            "expenditures." if value < 0 else "")
    return _result("free_cash_flow", p, value, RatioStatus.VALID, inputs, note)


def fcf_margin(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """FCF Margin = (operating_cash_flow - capex) / revenue. Unit: % (decimal). Cash flow.

    Edge cases: any input missing -> UNAVAILABLE; capex negative -> UNDEFINED (inconsistent
    sign); revenue zero or negative -> UNDEFINED. A negative FCF margin is VALID.
    """
    inputs = _get(p, "operating_cash_flow", "capex", "revenue")
    reason = _missing_reason(inputs)
    if reason:
        return _result("fcf_margin", p, None, RatioStatus.UNAVAILABLE, inputs, reason)
    if inputs["capex"] < 0:
        return _result("fcf_margin", p, None, RatioStatus.UNDEFINED, inputs,
                       _CAPEX_SIGN_REASON)
    fcf = inputs["operating_cash_flow"] - inputs["capex"]
    value, status, why = safe_divide(
        fcf, inputs["revenue"], require_positive_denominator=True,
        numerator_name="Free cash flow", denominator_name=_label("revenue"),
        negative_reason="Revenue is negative: margin not meaningful.")
    return _result("fcf_margin", p, value, status, inputs, why)


# --------------------------------------------------------------------------------------
# Growth
# --------------------------------------------------------------------------------------
def revenue_growth(p: FinancialPeriod, prev: Optional[FinancialPeriod] = None) -> RatioResult:
    """Revenue Growth = revenue / prev.revenue - 1. Unit: % (decimal). Category: growth.

    Only calculated when: prev exists, both periods are annual, prev.fiscal_year ==
    p.fiscal_year - 1, both use the same currency, and prior revenue > 0.
    Edge cases: no prior period / gap year / revenue missing -> UNAVAILABLE; not annual,
    different currency, prior revenue zero or negative, current revenue negative ->
    UNDEFINED. Currencies are never converted.
    """
    inputs: dict[str, Optional[float]] = {
        "revenue": p.get("revenue"),
        "prior_revenue": prev.get("revenue") if prev is not None else None,
    }

    def out(status: RatioStatus, text: str, value: Optional[float] = None) -> RatioResult:
        return _result("revenue_growth", p, value, status, inputs, text)

    if prev is None:
        return out(RatioStatus.UNAVAILABLE, "No prior-year period is available, so growth "
                   "cannot be calculated.")
    if not (p.is_annual and prev.is_annual):
        return out(RatioStatus.UNDEFINED, "Growth is only calculated between two annual "
                   "periods.")
    if prev.fiscal_year != p.fiscal_year - 1:
        return out(RatioStatus.UNAVAILABLE,
                   f"Prior period is FY{prev.fiscal_year}, not FY{p.fiscal_year - 1}: "
                   "year-on-year growth needs consecutive fiscal years.")
    if prev.currency != p.currency:
        return out(RatioStatus.UNDEFINED,
                   f"Different currencies ({prev.currency} vs {p.currency}); currencies are "
                   "never converted, so growth is not meaningful.")
    reason = _missing_reason(inputs)
    if reason:
        return out(RatioStatus.UNAVAILABLE, reason)
    if inputs["revenue"] < 0:
        return out(RatioStatus.UNDEFINED, "Current revenue is negative: growth not "
                   "meaningful.")
    ratio, status, why = safe_divide(
        inputs["revenue"], inputs["prior_revenue"], require_positive_denominator=True,
        numerator_name=_label("revenue"), denominator_name=_label("prior_revenue"),
        negative_reason="Prior-year revenue is negative: growth not meaningful.")
    if status != RatioStatus.VALID:
        return out(status, why)
    return out(RatioStatus.VALID, "", ratio - 1)


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------
RATIO_FUNCTIONS: dict[str, RatioFunction] = {
    "current_ratio": current_ratio,
    "cash_ratio": cash_ratio,
    "working_capital": working_capital,
    "total_debt": total_debt,
    "debt_to_equity": debt_to_equity,
    "debt_to_assets": debt_to_assets,
    "net_debt": net_debt,
    "net_debt_to_ebitda": net_debt_to_ebitda,
    "operating_margin": operating_margin,
    "net_profit_margin": net_profit_margin,
    "return_on_assets": return_on_assets,
    "interest_coverage": interest_coverage,
    "free_cash_flow": free_cash_flow,
    "fcf_margin": fcf_margin,
    "revenue_growth": revenue_growth,
}
STANDARD_RATIO_KEYS: list[str] = list(RATIO_FUNCTIONS)


def compute_ratios(p: FinancialPeriod,
                   prev: Optional[FinancialPeriod]) -> dict[str, RatioResult]:
    """All 15 standard ratios for one period; every key is always present."""
    return {key: fn(p, prev) for key, fn in RATIO_FUNCTIONS.items()}


def compute_all_ratios(f: CompanyFinancials) -> dict[int, dict[str, RatioResult]]:
    """fiscal_year -> ratio key -> RatioResult for every period.

    The previous fiscal year's period (fiscal_year - 1) is passed as `prev` when it exists;
    otherwise prev is None and revenue_growth is UNAVAILABLE.
    """
    return {p.fiscal_year: compute_ratios(p, f.period(p.fiscal_year - 1))
            for p in f.periods}
