"""Illustrative 0-100 financial risk SCREENING score for SolvIQ. Owned by Person 4.

This is NOT an agency credit rating, NOT a probability of default and NOT a lending decision
(see config.SCORE_DISCLAIMER). It turns the LATEST fiscal year's ratios into five factor
scores using the banded thresholds in SCORING_CONFIG.

Rules:
- Each factor scores a fraction (1.0 / 0.75 / 0.5 / 0.25 / 0) of its weight.
- A factor that cannot be scored (missing data) has points = None. If ANY factor is None the
  total is None: weights are never redistributed and missing data is never assumed good.
- Zero or negative equity -> leverage gets 0 points (a real weakness, not missing data).
- Banks/insurers (company.is_financial_institution) are not supported by this model.
"""
from __future__ import annotations

from typing import Optional

from src import config
from src.financial_calculations import RATIO_META, ebitda_value
from src.models import (CompanyFinancials, CreditScore, FactorScore, FinancialPeriod,
                        RatioResult, RatioStatus)

# --------------------------------------------------------------------------------------
# SCORING_CONFIG
#
# ILLUSTRATIVE DESIGN ASSUMPTIONS chosen by the team for this MVP. They are NOT validated
# banking standards and have NOT been calibrated against default data. Sensible thresholds
# differ by industry (e.g. utilities carry more leverage than software firms); this MVP
# applies one set of thresholds and only covers a NON-FINANCIAL corporate screening model.
#
# Structure:
#   weight     : maximum points of the factor (the five weights sum to 100)
#   ratios     : ratio key -> rule
#     direction: "higher" = higher is better, bands use  value >= threshold
#                "lower"  = lower is better,  bands use  value <= threshold
#     bands    : [(threshold, fraction of weight), ...] checked top to bottom; first match
#                wins. A value matching no band scores 0.
#   Percentages are decimals (0.15 = 15%), as in RatioResult.value.
# --------------------------------------------------------------------------------------
SCORING_CONFIG: dict = {
    "liquidity": {
        "weight": 20,
        "ratios": {
            # >= 2.0x full, >= 1.5x 75%, >= 1.0x 50%, >= 0.8x 25%, else 0
            "current_ratio": {"direction": "higher",
                              "bands": [(2.0, 1.0), (1.5, 0.75), (1.0, 0.5), (0.8, 0.25)]},
        },
    },
    "leverage": {
        "weight": 25,
        "ratios": {
            # <= 0.5x full, <= 1.0x 75%, <= 2.0x 50%, <= 3.0x 25%, else 0
            "debt_to_equity": {"direction": "lower",
                               "bands": [(0.5, 1.0), (1.0, 0.75), (2.0, 0.5), (3.0, 0.25)]},
            # <= 1.0x full, <= 2.0x 75%, <= 3.0x 50%, <= 4.0x 25%, else 0.
            # A negative value (net cash) is <= 1.0x and therefore gets full marks.
            "net_debt_to_ebitda": {"direction": "lower",
                                   "bands": [(1.0, 1.0), (2.0, 0.75), (3.0, 0.5),
                                             (4.0, 0.25)]},
        },
        # Both ratios valid -> the two fractions are averaged.
    },
    "profitability": {
        "weight": 20,
        "ratios": {
            # >= 15% full, >= 8% 75%, >= 3% 50%, >= 0% 25%, else 0
            "operating_margin": {"direction": "higher",
                                 "bands": [(0.15, 1.0), (0.08, 0.75), (0.03, 0.5),
                                           (0.0, 0.25)]},
        },
    },
    "coverage": {
        "weight": 20,
        "ratios": {
            # >= 8x full, >= 4x 75%, >= 2x 50%, >= 1x 25%, else 0
            "interest_coverage": {"direction": "higher",
                                  "bands": [(8.0, 1.0), (4.0, 0.75), (2.0, 0.5), (1.0, 0.25)]},
        },
    },
    "cash_flow": {
        "weight": 15,
        "ratios": {
            # >= 10% full, >= 5% 75%, >= 0% 50%, else 0
            "fcf_margin": {"direction": "higher",
                           "bands": [(0.10, 1.0), (0.05, 0.75), (0.0, 0.5)]},
        },
    },
}
FACTOR_ORDER: list[str] = ["liquidity", "leverage", "profitability", "coverage", "cash_flow"]
FACTOR_LABELS: dict[str, str] = {"liquidity": "Liquidity", "leverage": "Leverage",
                                 "profitability": "Profitability", "coverage": "Coverage",
                                 "cash_flow": "Cash flow"}


# --------------------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------------------
def _unit(key: str) -> str:
    return RATIO_META[key][2]


_SENTENCE_NAMES: dict[str, str] = {
    "current_ratio": "Current ratio", "debt_to_equity": "Debt to equity",
    "net_debt_to_ebitda": "Net debt / EBITDA", "operating_margin": "Operating margin",
    "interest_coverage": "Interest coverage", "fcf_margin": "FCF margin",
}


def _ratio_name(key: str) -> str:
    """Ratio name for use inside sentences, e.g. 'Current ratio'."""
    return _SENTENCE_NAMES.get(key, RATIO_META[key][0])


def fmt_value(value: float, unit: str) -> str:
    """Ratio display: 1.846 -> '1.85x'; 0.15 -> '15.0%'. Money amounts use fmt_money."""
    if unit == "%":
        return f"{value * 100:.1f}%"
    return f"{value:.2f}x"


def _fmt_number(threshold: float, unit: str) -> str:
    """Threshold without its unit: 2.0 -> '2.0' (x), 0.15 -> '15' (%)."""
    return f"{threshold * 100:g}" if unit == "%" else f"{threshold:.1f}"


def _suffix(unit: str) -> str:
    return "%" if unit == "%" else "x"


def _fmt_threshold(threshold: float, unit: str) -> str:
    return _fmt_number(threshold, unit) + _suffix(unit)


def _fmt_points(points: float) -> str:
    return f"{points:g}"


def fmt_money(value: float, currency: str) -> str:
    """Compact DISPLAY text for a full-unit money amount (stored values are never changed).

    abs >= 1 billion -> '-1.2bn USD'; abs >= 1 million -> '-500.0m USD';
    otherwise -> '-12,345 USD'.
    The unit is chosen AFTER rounding, so 999,960,000 (999.96m -> 1,000.0m) shows as
    '1.0bn USD' and 999,999.6 (rounds to 1,000,000) shows as '1.0m USD'.
    """
    if abs(round(value / 1_000_000, 1)) >= 1_000:
        return f"{value / 1_000_000_000:.1f}bn {currency}"
    if abs(round(value)) >= 1_000_000:
        return f"{value / 1_000_000:.1f}m {currency}"
    return f"{value:,.0f} {currency}"


# --------------------------------------------------------------------------------------
# Banding
# --------------------------------------------------------------------------------------
def score_ratio(key: str, value: float, rule: Optional[dict] = None) -> tuple[float, str]:
    """Fraction (0..1) earned by a VALID ratio value, and a description of its band.

    `rule` defaults to the rule for `key` in SCORING_CONFIG.
    Bands use >= (direction "higher") or <= (direction "lower") exactly.
    """
    rule = rule or _rule_for(key)
    unit = _unit(key)
    bands = rule["bands"]
    higher = rule["direction"] == "higher"
    for i, (threshold, fraction) in enumerate(bands):
        hit = value >= threshold if higher else value <= threshold
        if not hit:
            continue
        if i == 0:
            t = _fmt_threshold(threshold, unit)
            text = f"at or above {t}" if higher else f"at or below {t}"
        else:
            a, b = _fmt_number(threshold, unit), _fmt_number(bands[i - 1][0], unit)
            low, high = (a, b) if higher else (b, a)
            text = f"in the {low}-{high}{_suffix(unit)} band"
        return fraction, text
    last = _fmt_threshold(bands[-1][0], unit)
    return 0.0, (f"below {last}" if higher else f"above {last}")


def _rule_for(key: str) -> dict:
    for factor in SCORING_CONFIG.values():
        if key in factor["ratios"]:
            return factor["ratios"][key]
    raise KeyError(f"No scoring rule for ratio {key!r}")


def risk_category(total: float) -> str:
    """Category label from config.RISK_BANDS (first band whose minimum is <= total)."""
    for minimum, label in config.RISK_BANDS:
        if total >= minimum:
            return label
    return config.RISK_BANDS[-1][1]


# --------------------------------------------------------------------------------------
# Factor scoring
# --------------------------------------------------------------------------------------
def _not_valid_text(r: Optional[RatioResult], key: str) -> str:
    if r is None:
        return f"{_ratio_name(key)} was not calculated."
    return f"{_ratio_name(key)} is {r.status.value}: {r.explanation}".strip()


def _factor(factor: str, points: Optional[float], ratios_used: list[str],
            explanation: str) -> FactorScore:
    return FactorScore(factor=factor, max_points=SCORING_CONFIG[factor]["weight"],
                       points=points, ratios_used=ratios_used, explanation=explanation)


def _score_single(factor: str, key: str, r: Optional[RatioResult]) -> FactorScore:
    """Factor driven by one ratio; None if that ratio is not VALID."""
    weight = SCORING_CONFIG[factor]["weight"]
    if r is None or r.status != RatioStatus.VALID:
        return _factor(factor, None, [key],
                       f"{_not_valid_text(r, key)} {FACTOR_LABELS[factor]} cannot be scored.")
    fraction, band = score_ratio(key, r.value)
    points = fraction * weight
    return _factor(factor, points, [key],
                   f"{_ratio_name(key)} {fmt_value(r.value, _unit(key))} is {band}: "
                   f"{_fmt_points(points)} of {weight} points.")


def _score_coverage(ratios: dict[str, RatioResult], p: FinancialPeriod) -> FactorScore:
    """Interest coverage, with the zero-interest-expense rule."""
    r = ratios.get("interest_coverage")
    zero_interest = (r is not None and r.status == RatioStatus.UNDEFINED
                     and r.inputs.get("interest_expense") == 0)
    if not zero_interest:
        return _score_single("coverage", "interest_coverage", r)
    weight = SCORING_CONFIG["coverage"]["weight"]
    nd = ratios.get("net_debt")
    used = ["interest_coverage", "net_debt"]
    if nd is not None and nd.status == RatioStatus.VALID and nd.value <= 0:
        return _factor("coverage", float(weight), used,
                       f"No interest expense reported and net debt is "
                       f"{fmt_money(nd.value, p.currency)} "
                       f"(net cash position): no debt to service, {weight} of {weight} "
                       "points.")
    if nd is not None and nd.status == RatioStatus.VALID:
        why = (f"net debt is positive ({fmt_money(nd.value, p.currency)}), so zero "
               "interest expense is "
               "inconsistent with the debt reported")
    else:
        why = "net debt cannot be calculated, so it is unknown whether there is debt to service"
    return _factor("coverage", None, used,
                   f"No interest expense reported, but {why}. Coverage cannot be scored.")


def _score_leverage(ratios: dict[str, RatioResult], p: FinancialPeriod) -> FactorScore:
    """Leverage: average of debt_to_equity and net_debt_to_ebitda fractions.

    - Equity <= 0 -> 0 points (checked directly on total_equity).
    - net_debt_to_ebitda UNDEFINED because EBITDA <= 0 with positive net debt -> that
      component scores 0 and is averaged as normal.
    - Fall back to the single remaining ratio only when the other is UNAVAILABLE, or when
      EBITDA <= 0 with a net cash position.
    """
    weight = SCORING_CONFIG["leverage"]["weight"]
    used = ["debt_to_equity", "net_debt_to_ebitda"]
    equity = p.get("total_equity")
    if equity is not None and equity <= 0:
        kind = "negative" if equity < 0 else "zero"
        return _factor("leverage", 0.0, used,
                       f"Shareholders' equity is {kind} ({fmt_money(equity, p.currency)}): "
                       "this is a real "
                       f"balance-sheet weakness, not missing data. 0 of {weight} points.")

    parts: list[tuple[float, str]] = []   # (fraction, text) of each scored component
    notes: list[str] = []                 # components that could not be used
    de = ratios.get("debt_to_equity")
    if de is not None and de.status == RatioStatus.VALID:
        frac, band = score_ratio("debt_to_equity", de.value)
        parts.append((frac, f"debt to equity {fmt_value(de.value, 'x')} is {band} "
                            f"({frac:.0%})"))
    else:
        notes.append(_not_valid_text(de, "debt_to_equity"))

    nde = ratios.get("net_debt_to_ebitda")
    ebitda, _ = ebitda_value(p)
    nd = ratios.get("net_debt")
    if nde is not None and nde.status == RatioStatus.VALID:
        frac, band = score_ratio("net_debt_to_ebitda", nde.value)
        parts.append((frac, f"net debt / EBITDA {fmt_value(nde.value, 'x')} is {band} "
                            f"({frac:.0%})"))
    elif (nde is not None and nde.status == RatioStatus.UNDEFINED and ebitda is not None
          and ebitda <= 0 and nd is not None and nd.status == RatioStatus.VALID):
        if nd.value > 0:
            parts.append((0.0, f"net debt / EBITDA scores 0% because EBITDA is not positive "
                               f"({fmt_money(ebitda, p.currency)}) while net debt is "
                               f"positive ({fmt_money(nd.value, p.currency)}): "
                               "a real weakness, not missing data"))
        else:
            notes.append(f"Net debt / EBITDA is not used: EBITDA is not positive "
                         f"({fmt_money(ebitda, p.currency)}) but the company has a net "
                         "cash position.")
    else:
        notes.append(_not_valid_text(nde, "net_debt_to_ebitda"))

    if not parts:
        return _factor("leverage", None, used,
                       " ".join(notes) + " Leverage cannot be scored.")
    fraction = sum(f for f, _ in parts) / len(parts)
    points = fraction * weight
    how = "average of the two" if len(parts) == 2 else "only one leverage ratio usable"
    text = "; ".join(t for _, t in parts)
    explanation = (f"{text[0].upper()}{text[1:]}. {how.capitalize()}: {fraction:.1%} of "
                   f"{weight} = {_fmt_points(points)} of {weight} points.")
    if notes:
        explanation += " " + " ".join(notes)
    return _factor("leverage", points, used, explanation)


def score_factors(ratios: dict[str, RatioResult], p: FinancialPeriod) -> list[FactorScore]:
    """The five factor scores for one period's ratios, in FACTOR_ORDER."""
    return [
        _score_single("liquidity", "current_ratio", ratios.get("current_ratio")),
        _score_leverage(ratios, p),
        _score_single("profitability", "operating_margin", ratios.get("operating_margin")),
        _score_coverage(ratios, p),
        _score_single("cash_flow", "fcf_margin", ratios.get("fcf_margin")),
    ]


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------
def compute_credit_score(ratios: dict[int, dict[str, RatioResult]],
                         f: CompanyFinancials) -> CreditScore:
    """Illustrative score from the LATEST fiscal year's ratios (f.periods[0])."""
    p = f.latest()
    if p is None:
        return CreditScore(sufficient_data=False,
                           explanation=f"{config.INSUFFICIENT_SCORE_LABEL}. No financial "
                                       "periods are available.")
    factors = score_factors(ratios.get(p.fiscal_year, {}), p)

    if f.company.is_financial_institution:
        return CreditScore(sufficient_data=False, factors=factors,
                           explanation=config.FINANCIAL_INSTITUTION_MESSAGE)

    missing = [fs for fs in factors if fs.points is None]
    if missing:
        details = " ".join(f"{FACTOR_LABELS[fs.factor]}: {fs.explanation}" for fs in missing)
        return CreditScore(
            sufficient_data=False, factors=factors,
            explanation=(f"{config.INSUFFICIENT_SCORE_LABEL}. FY{p.fiscal_year}: "
                         f"{len(missing)} of {len(factors)} factors could not be scored. "
                         f"{details} Partial factor scores are shown for information only; "
                         "missing data is never assumed to be good and weights are not "
                         "redistributed."))

    total = sum(fs.points for fs in factors)
    category = risk_category(total)
    arithmetic = " + ".join(_fmt_points(fs.points) for fs in factors)
    return CreditScore(
        total=total, category=category, sufficient_data=True, factors=factors,
        explanation=(f"FY{p.fiscal_year} illustrative screening score: {arithmetic} = "
                     f"{_fmt_points(total)} out of 100 ({category}). "
                     f"{config.SCORE_DISCLAIMER}"))
