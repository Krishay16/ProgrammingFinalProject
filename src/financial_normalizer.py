"""Owned by Person 2: SEC companyfacts JSON -> CompanyFinancials.

Turns the SEC "companyfacts" XBRL JSON (https://data.sec.gov/api/xbrl/companyfacts/...)
into the shared ``CompanyFinancials`` model. The selection policy is also documented in
docs/data-sources.md ("Selection policy"); keep the two in sync.

Selection policy (summary)
--------------------------
1. Only the ``us-gaap`` taxonomy is read. No ``us-gaap`` (e.g. IFRS / 20-F filers) or empty
   facts -> ``periods == []`` plus a warning. Ordinary data problems never raise.
2. Annual facts only: ``form`` in {"10-K", "10-K/A"} and ``fp == "FY"``. The ``fy`` field is
   the fiscal year of the FILING (10-Ks repeat prior years), so it is never used to identify a
   period; periods are identified by their ``end`` date (and ``start`` for flow items).
3. Flow items (income statement, cash flow) must cover about one year: ``end - start`` between
   350 and 380 days (accepts 52/53-week years, rejects quarters even if tagged fp=FY).
   Balance-sheet items are instants (no ``start``) taken ONLY at exactly a canonical end date.
4. Canonical period ends = ``end`` dates of ~1-year annual facts of the core flow tags
   (net income, revenue candidates, operating income, operating cash flow).
5. "Core items": an end date qualifies only if NetIncomeLoss (~1-year flow) AND Assets
   (instant at exactly that end) both exist in the period currency. Revenue may be missing.
6. fiscal_year = calendar year of the period end. If two qualifying ends fall in the same
   calendar year (fiscal-year-end change, 52/53-week year ending 1-2 Jan), the later end is
   kept and a warning is added. The latest ``max_periods`` ends are kept, NEWEST FIRST.
7. Duplicates for the same tag + end (+ currency): the most recently ``filed`` fact wins (this
   picks up 10-K/A amendments and restatements in later 10-Ks); a tie is broken by the highest
   accession number (``accn``).
8. Tag choice per field: each field has an ordered list of candidates (``FIELD_CANDIDATES``:
   reported tags first, then derivations). First, the highest-priority candidate that has a
   value for ALL selected periods is used for every period (consistent series). Only if no
   single candidate covers all periods, each period uses its own first-found candidate, and a
   warning is added if the tags used differ between periods.
9. Currency: only ISO currency unit keys (3 capital letters, e.g. "USD") are read; "USD/shares"
   etc. are ignored. The period currency is USD when net income is reported in USD, otherwise
   the single other currency found. A field that only exists in another currency is left
   missing with a warning: two currencies are never mixed in one period and never converted.
10. Signs: capex and interest_expense are stored as positive amounts (``abs``); if the reported
    value was negative, ``Provenance.note`` says the sign was flipped. Other values keep their
    reported sign.
11. Missing tags give ``None`` (never 0), plus one warning per period listing missing fields.
    ``ebitda`` is always left ``None`` here (the engine derives it from EBIT + D&A).
12. Provenance: source SEC_EDGAR, ``source_ref`` = the companyfacts URL with the padded CIK,
    ``location`` = "<form> accn <accn>", ``filing_date`` = filed date, ``tag`` = tag used,
    ``original_text`` = the raw reported number, verification SOURCE_STRUCTURED. Derived values
    have origin DERIVED and a note listing their component tags and filings.
13. Period metadata (``period_start``, ``form_type``, ``filing_date``) comes from the net income
    fact selected for that period, i.e. the MOST RECENT filing that reported the period. For an
    older year this can be a later 10-K that repeats it as a comparative.
14. Values are already in full currency units in XBRL: ``original_units = Units.UNITS``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from src.models import (
    ALL_FIELDS,
    FIELD_LABELS,
    CompanyFinancials,
    CompanyInfo,
    FinancialPeriod,
    FinancialValue,
    Provenance,
    SourceType,
    Units,
    ValueOrigin,
    VerificationStatus,
)
from src.sec_client import COMPANY_FACTS_URL, pad_cik

ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
MIN_ANNUAL_DAYS = 350
MAX_ANNUAL_DAYS = 380
PREFERRED_CURRENCY = "USD"
_CURRENCY_UNIT = re.compile(r"^[A-Z]{3}$")

# --------------------------------------------------------------------------- tag lists

#: Ordered candidate tags per field for fields that are taken directly from one tag.
#: First candidate found wins (see the consistency rule in the module docstring).
TAG_MAP: dict[str, list[str]] = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "ebit": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating",
                         "InterestExpenseDebt"],
    "net_income": ["NetIncomeLoss"],
    "depreciation_amortization": ["DepreciationDepletionAndAmortization",
                                  "DepreciationAndAmortization",
                                  "DepreciationAmortizationAndAccretionNet"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "current_assets": ["AssetsCurrent"],
    "total_assets": ["Assets"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "total_liabilities": ["Liabilities"],
    "total_equity": ["StockholdersEquity",
                     "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "short_term_debt": ["DebtCurrent"],
    "long_term_debt": ["LongTermDebtNoncurrent"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "investing_cash_flow": ["NetCashProvidedByUsedInInvestingActivities"],
    "financing_cash_flow": ["NetCashProvidedByUsedInFinancingActivities"],
}

#: Component tags used only by derivations.
SHORT_TERM_DEBT_COMPONENTS = ["LongTermDebtCurrent", "CommercialPaper", "ShortTermBorrowings"]
LONG_TERM_DEBT_TOTAL = "LongTermDebt"
LONG_TERM_DEBT_CURRENT = "LongTermDebtCurrent"
LIABILITIES_AND_EQUITY = "LiabilitiesAndStockholdersEquity"
EQUITY_INCL_NCI = "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
EQUITY_PARENT = "StockholdersEquity"
RESTRICTED_CASH_TAG = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"

#: Tags whose facts are durations (income statement / cash flow). Everything else is an instant.
FLOW_FIELDS = frozenset({
    "revenue", "cost_of_revenue", "gross_profit", "ebit", "interest_expense", "net_income",
    "depreciation_amortization", "operating_cash_flow", "capex", "investing_cash_flow",
    "financing_cash_flow",
})
FLOW_TAGS = frozenset(t for f in FLOW_FIELDS for t in TAG_MAP[f])
INSTANT_TAGS = frozenset(
    {t for f, tags in TAG_MAP.items() if f not in FLOW_FIELDS for t in tags}
    | set(SHORT_TERM_DEBT_COMPONENTS)
    | {LONG_TERM_DEBT_TOTAL, LIABILITIES_AND_EQUITY, EQUITY_INCL_NCI, EQUITY_PARENT}
)
ALL_TAGS = FLOW_TAGS | INSTANT_TAGS

#: Flow tags whose ~1-year 10-K end dates define candidate fiscal year ends.
CORE_FLOW_TAGS = (["NetIncomeLoss", "OperatingIncomeLoss",
                   "NetCashProvidedByUsedInOperatingActivities"] + TAG_MAP["revenue"])
NET_INCOME_TAG = "NetIncomeLoss"
TOTAL_ASSETS_TAG = "Assets"

#: Fields stored as positive amounts regardless of the reported sign.
POSITIVE_FIELDS = frozenset({"capex", "interest_expense"})

#: Fields the normalizer never fills (derived later by the engine).
ENGINE_DERIVED_FIELDS = frozenset({"ebitda"})


# --------------------------------------------------------------------------- internal types

@dataclass(frozen=True)
class _Fact:
    """One usable annual XBRL fact."""
    tag: str
    unit: str
    val: float
    end: date
    start: Optional[date]
    form: str
    filed: date
    accn: str

    @property
    def location(self) -> str:
        return f"{self.form} accn {self.accn}"


@dataclass(frozen=True)
class _Resolved:
    """A field value chosen for one period, before conversion to FinancialValue."""
    value: float
    tag: str
    origin: ValueOrigin
    location: str
    filing_date: date
    original_text: Optional[str] = None
    note: Optional[str] = None


# (tag, end, unit) -> best fact
_FactIndex = dict[tuple[str, date, str], _Fact]


@dataclass(frozen=True)
class _PeriodCtx:
    """Lookup context for one selected period."""
    end: date
    currency: str
    index: _FactIndex

    def get(self, tag: str) -> Optional[_Fact]:
        return self.index.get((tag, self.end, self.currency))


@dataclass(frozen=True)
class _Candidate:
    """A way to obtain a field: either a reported tag or a derivation."""
    name: str
    resolve: Callable[[_PeriodCtx], Optional[_Resolved]]


# --------------------------------------------------------------------------- parsing

def _parse_date(text: object) -> Optional[date]:
    """ISO date string -> date, or None if absent/invalid."""
    if not isinstance(text, str):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _duration_days(start: date, end: date) -> int:
    """Length of a duration fact in days (end - start)."""
    return (end - start).days


def _is_annual_duration(start: Optional[date], end: date) -> bool:
    """True if a duration covers about one year (350-380 days, so 52/53-week years pass)."""
    return start is not None and MIN_ANNUAL_DAYS <= _duration_days(start, end) <= MAX_ANNUAL_DAYS


def _parse_fact(tag: str, unit: str, raw: object) -> Optional[_Fact]:
    """Return a _Fact for an annual 10-K/10-K/A FY fact, or None if it is not usable."""
    if not isinstance(raw, dict):
        return None
    if raw.get("form") not in ANNUAL_FORMS or raw.get("fp") != "FY":
        return None
    val = raw.get("val")
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
        return None
    end = _parse_date(raw.get("end"))
    filed = _parse_date(raw.get("filed"))
    if end is None or filed is None:
        return None
    start = _parse_date(raw.get("start"))
    is_flow = tag in FLOW_TAGS
    if is_flow and not _is_annual_duration(start, end):
        return None
    if not is_flow and "start" in raw:
        return None  # balance-sheet items must be instants
    return _Fact(tag=tag, unit=unit, val=float(val), end=end, start=start,
                 form=str(raw.get("form")), filed=filed, accn=str(raw.get("accn") or ""))


def _is_better(new: _Fact, old: _Fact) -> bool:
    """Duplicate rule: most recently filed wins; tie -> highest accession number."""
    return (new.filed, new.accn) > (old.filed, old.accn)


def _build_index(us_gaap: dict) -> _FactIndex:
    """Index the best annual fact per (tag, end date, currency) for the tags we use."""
    index: _FactIndex = {}
    for tag in ALL_TAGS:
        entry = us_gaap.get(tag)
        units = entry.get("units") if isinstance(entry, dict) else None
        if not isinstance(units, dict):
            continue
        for unit, rows in units.items():
            if not _CURRENCY_UNIT.match(str(unit)) or not isinstance(rows, list):
                continue
            for raw in rows:
                fact = _parse_fact(tag, unit, raw)
                if fact is None:
                    continue
                key = (tag, fact.end, unit)
                if key not in index or _is_better(fact, index[key]):
                    index[key] = fact
    return index


# --------------------------------------------------------------------------- period selection

def _currencies_for(index: _FactIndex, tag: str, end: date) -> list[str]:
    """Currencies in which ``tag`` has a fact at ``end`` (sorted)."""
    return sorted(unit for (t, e, unit) in index if t == tag and e == end)


def _period_currency(index: _FactIndex, end: date) -> Optional[str]:
    """USD if net income is reported in USD at this end, else the single other currency."""
    currencies = _currencies_for(index, NET_INCOME_TAG, end)
    if PREFERRED_CURRENCY in currencies:
        return PREFERRED_CURRENCY
    return currencies[0] if len(currencies) == 1 else None


def _find_period_ends(index: _FactIndex) -> list[date]:
    """Candidate fiscal year ends: ends of ~1-year 10-K facts of core flow tags, newest first."""
    ends = {e for (tag, e, _unit) in index if tag in CORE_FLOW_TAGS}
    return sorted(ends, reverse=True)


def _select_periods(index: _FactIndex, max_periods: int,
                    warnings: list[str]) -> list[_PeriodCtx]:
    """Qualifying period ends (core items present), one per fiscal year, newest first."""
    qualified: list[_PeriodCtx] = []
    for end in _find_period_ends(index):
        currency = _period_currency(index, end)
        if currency is None:
            if len(_currencies_for(index, NET_INCOME_TAG, end)) > 1:
                warnings.append(f"Period ending {end.isoformat()} skipped: net income is "
                                "reported in several currencies and none is USD.")
            continue
        ctx = _PeriodCtx(end=end, currency=currency, index=index)
        if ctx.get(NET_INCOME_TAG) is None or ctx.get(TOTAL_ASSETS_TAG) is None:
            continue
        qualified.append(ctx)

    by_year: dict[int, _PeriodCtx] = {}
    for ctx in qualified:  # newest first, so the first one per year is the later end
        year = ctx.end.year
        if year in by_year:
            warnings.append(
                f"Two fiscal year ends fall in {year} ({by_year[year].end.isoformat()} and "
                f"{ctx.end.isoformat()}), e.g. a change of fiscal year end or a 52/53-week "
                f"year. Kept the later one ({by_year[year].end.isoformat()}) and ignored "
                f"{ctx.end.isoformat()}.")
            continue
        by_year[year] = ctx
    return sorted(by_year.values(), key=lambda c: c.end, reverse=True)[:max_periods]


# --------------------------------------------------------------------------- field resolvers

def _reported(tag: str, note: Optional[str] = None) -> _Candidate:
    """Candidate that takes the value of one reported tag."""
    def resolve(ctx: _PeriodCtx) -> Optional[_Resolved]:
        fact = ctx.get(tag)
        if fact is None:
            return None
        return _Resolved(value=fact.val, tag=tag, origin=ValueOrigin.REPORTED,
                         location=fact.location, filing_date=fact.filed,
                         original_text=_raw_text(fact.val), note=note)
    return _Candidate(name=tag, resolve=resolve)


def _raw_text(val: float) -> str:
    """Reported number as text (integers without a trailing .0)."""
    return str(int(val)) if val.is_integer() else repr(val)


def _component_note(facts: list[_Fact]) -> str:
    """Human-readable list of the component facts of a derived value."""
    return "; ".join(f"{f.tag} = {_raw_text(f.val)} ({f.location}, filed {f.filed})"
                     for f in facts)


def _derived(value: float, facts: list[_Fact], tag: str, explanation: str) -> _Resolved:
    """Build a DERIVED value from its components (provenance of the latest-filed one)."""
    latest = max(facts, key=lambda f: (f.filed, f.accn))
    return _Resolved(value=value, tag=tag, origin=ValueOrigin.DERIVED,
                     location=latest.location, filing_date=latest.filed,
                     note=f"{explanation} Components: {_component_note(facts)}.")


def _short_term_debt_from_components(ctx: _PeriodCtx) -> Optional[_Resolved]:
    """Sum of whichever of LongTermDebtCurrent, CommercialPaper, ShortTermBorrowings exist.

    Only used when DebtCurrent is absent (so nothing is counted twice). None if no component
    is present. Lease liabilities and accounts payable are never included.
    """
    facts = [f for f in (ctx.get(t) for t in SHORT_TERM_DEBT_COMPONENTS) if f is not None]
    if not facts:
        return None
    used = [f.tag for f in facts]
    return _derived(sum(f.val for f in facts), facts, " + ".join(used),
                    "Derived: DebtCurrent not reported, so short-term debt = sum of the "
                    f"components found ({', '.join(used)}).")


def _long_term_debt_from_total(ctx: _PeriodCtx) -> Optional[_Resolved]:
    """LongTermDebt - LongTermDebtCurrent; None unless BOTH are present."""
    total, current = ctx.get(LONG_TERM_DEBT_TOTAL), ctx.get(LONG_TERM_DEBT_CURRENT)
    if total is None or current is None:
        return None
    return _derived(total.val - current.val, [total, current],
                    f"{LONG_TERM_DEBT_TOTAL} - {LONG_TERM_DEBT_CURRENT}",
                    "Derived: LongTermDebtNoncurrent not reported, so long-term debt = "
                    "LongTermDebt minus LongTermDebtCurrent.")


def _total_liabilities_from_balance(ctx: _PeriodCtx) -> Optional[_Resolved]:
    """LiabilitiesAndStockholdersEquity - equity (equity INCLUDING NCI preferred)."""
    total = ctx.get(LIABILITIES_AND_EQUITY)
    if total is None:
        return None
    equity = ctx.get(EQUITY_INCL_NCI)
    caveat = ""
    if equity is None:
        equity = ctx.get(EQUITY_PARENT)
        caveat = (" Equity including non-controlling interest was not reported, so the result "
                  "may include non-controlling interest.")
    if equity is None:
        return None
    return _derived(total.val - equity.val, [total, equity],
                    f"{LIABILITIES_AND_EQUITY} - {equity.tag}",
                    "Derived: Liabilities not reported, so total liabilities = total "
                    f"liabilities and equity minus {equity.tag}.{caveat}")


def _candidates_for(field: str) -> list[_Candidate]:
    """Ordered candidates for a field: reported tags first, then derivations."""
    if field == "cash":
        return [_reported("CashAndCashEquivalentsAtCarryingValue"),
                _reported(RESTRICTED_CASH_TAG,
                          note="Includes restricted cash and restricted cash equivalents "
                               "(CashAndCashEquivalentsAtCarryingValue not reported).")]
    candidates = [_reported(tag) for tag in TAG_MAP.get(field, [])]
    if field == "short_term_debt":
        candidates.append(_Candidate("short-term debt components",
                                     _short_term_debt_from_components))
    elif field == "long_term_debt":
        candidates.append(_Candidate("LongTermDebt - LongTermDebtCurrent",
                                     _long_term_debt_from_total))
    elif field == "total_liabilities":
        candidates.append(_Candidate("LiabilitiesAndStockholdersEquity - equity",
                                     _total_liabilities_from_balance))
    return candidates


def _resolve_field(field: str, periods: list[_PeriodCtx]) -> list[Optional[_Resolved]]:
    """Resolve one field for all periods using the consistency rule.

    1. The highest-priority candidate with a value in EVERY period is used for all periods.
    2. Otherwise each period uses its own first candidate that has a value.
    """
    candidates = _candidates_for(field)
    for cand in candidates:
        results = [cand.resolve(ctx) for ctx in periods]
        if results and all(r is not None for r in results):
            return results
    resolved: list[Optional[_Resolved]] = []
    for ctx in periods:
        resolved.append(next((r for r in (c.resolve(ctx) for c in candidates)
                              if r is not None), None))
    return resolved


def _apply_sign_convention(field: str, res: _Resolved) -> _Resolved:
    """capex / interest_expense are stored positive; note a flipped sign."""
    if field not in POSITIVE_FIELDS or res.value >= 0:
        return res
    flip = (f"Reported value was negative ({_raw_text(res.value)}); sign flipped to store "
            "the amount as positive per the team sign convention.")
    note = f"{res.note} {flip}" if res.note else flip
    return _Resolved(value=abs(res.value), tag=res.tag, origin=res.origin,
                     location=res.location, filing_date=res.filing_date,
                     original_text=res.original_text, note=note)


def _to_financial_value(res: Optional[_Resolved], source_ref: str) -> FinancialValue:
    """Convert a resolved value (or None) into the shared FinancialValue model."""
    if res is None:
        return FinancialValue()
    return FinancialValue(value=res.value, provenance=Provenance(
        source_type=SourceType.SEC_EDGAR, source_ref=source_ref, location=res.location,
        original_text=res.original_text, tag=res.tag, origin=res.origin,
        verification=VerificationStatus.SOURCE_STRUCTURED, filing_date=res.filing_date,
        note=res.note))


# --------------------------------------------------------------------------- warnings

def _tag_switch_warning(field: str, periods: list[_PeriodCtx],
                        resolved: list[Optional[_Resolved]]) -> Optional[str]:
    """Warning text if the tag used for a field differs between periods."""
    used = [(ctx.end.year, r.tag) for ctx, r in zip(periods, resolved) if r is not None]
    if len({tag for _y, tag in used}) <= 1:
        return None
    detail = "; ".join(f"FY{year}: {tag}" for year, tag in used)
    return (f"{FIELD_LABELS[field]}: the SEC tag used differs between periods ({detail}). "
            "Definitions may not be identical; check comparability.")


def _other_currency_warning(field: str, ctx: _PeriodCtx) -> Optional[str]:
    """Warning if a missing field exists at this end only in a different currency."""
    tags = {t for t in TAG_MAP.get(field, [])}
    if field == "short_term_debt":
        tags |= set(SHORT_TERM_DEBT_COMPONENTS)
    others = sorted({unit for (t, e, unit) in ctx.index
                     if t in tags and e == ctx.end and unit != ctx.currency})
    if not others:
        return None
    return (f"FY{ctx.end.year}: {FIELD_LABELS[field]} is reported only in "
            f"{', '.join(others)}, but this period is in {ctx.currency}. It was left missing "
            "because currencies are never mixed or converted.")


def _missing_warning(period: FinancialPeriod) -> Optional[str]:
    """One warning listing the fields that could not be found for a period."""
    missing = [f for f in period.missing_fields() if f not in ENGINE_DERIVED_FIELDS]
    if not missing:
        return None
    labels = ", ".join(FIELD_LABELS[f] for f in missing)
    return (f"FY{period.fiscal_year}: not found in the SEC data (left blank, not zero): "
            f"{labels}.")


# --------------------------------------------------------------------------- public API

def _source_ref(facts: dict, company: CompanyInfo) -> str:
    """Companyfacts URL with the padded CIK (from CompanyInfo, else from the JSON)."""
    for raw in (company.cik, facts.get("cik") if isinstance(facts, dict) else None):
        if raw is None:
            continue
        try:
            return COMPANY_FACTS_URL.format(cik=pad_cik(raw))
        except ValueError:
            continue
    return "SEC EDGAR companyfacts (CIK unknown)"


def _no_data_warning(facts: object) -> str:
    """Explain why no us-gaap data could be used."""
    taxonomies = facts.get("facts") if isinstance(facts, dict) else None
    if isinstance(taxonomies, dict) and "ifrs-full" in taxonomies:
        return ("The SEC data for this company uses IFRS (ifrs-full), not US GAAP. Only US "
                "GAAP figures can be imported automatically; please use PDF upload or manual "
                "entry.")
    return ("No US GAAP (us-gaap) financial data was found in the SEC company facts for this "
            "company; please use PDF upload or manual entry.")


def normalize_company_facts(facts: dict, company: CompanyInfo,
                            max_periods: int = 3) -> CompanyFinancials:
    """Convert SEC companyfacts JSON into the shared data model.

    Applies the selection policy described in the module docstring (annual 10-K/10-K/A FY
    facts, periods identified by end date, ~1-year durations, latest-filed duplicates,
    consistent tags across periods, no currency mixing, missing = None).

    Args:
        facts: parsed companyfacts JSON (``{"cik": ..., "facts": {"us-gaap": {...}}}``).
        company: company identity (copied into the result; ``reporting_framework`` is set to
            "US GAAP" when periods are found and it was not set).
        max_periods: maximum number of fiscal years to return (latest first); values below
            1 are treated as 1.

    Returns:
        CompanyFinancials with ``source_type=SEC_EDGAR``, periods NEWEST FIRST and
        plain-English warnings. Never raises for ordinary data problems: empty facts, no
        us-gaap or no annual data give ``periods == []`` and a warning.
    """
    warnings: list[str] = []
    max_periods = max(1, int(max_periods))
    source_ref = _source_ref(facts, company)
    taxonomies = facts.get("facts") if isinstance(facts, dict) else None
    us_gaap = taxonomies.get("us-gaap") if isinstance(taxonomies, dict) else None

    if not isinstance(us_gaap, dict) or not us_gaap:
        warnings.append(_no_data_warning(facts))
        return CompanyFinancials(company=company, source_type=SourceType.SEC_EDGAR,
                                 warnings=warnings)

    index = _build_index(us_gaap)
    selected = _select_periods(index, max_periods, warnings)
    if not selected:
        warnings.append("No annual 10-K financial statements with both net income and total "
                        "assets for a full fiscal year were found in the SEC data; please use "
                        "PDF upload or manual entry.")
        return CompanyFinancials(company=company, source_type=SourceType.SEC_EDGAR,
                                 warnings=warnings)

    values: dict[str, list[Optional[_Resolved]]] = {}
    for field in ALL_FIELDS:
        if field in ENGINE_DERIVED_FIELDS:
            values[field] = [None] * len(selected)
            continue
        resolved = _resolve_field(field, selected)
        values[field] = [_apply_sign_convention(field, r) if r else None for r in resolved]
        switch = _tag_switch_warning(field, selected, values[field])
        if switch:
            warnings.append(switch)

    periods: list[FinancialPeriod] = []
    for i, ctx in enumerate(selected):
        ni = ctx.get(NET_INCOME_TAG)  # guaranteed by _select_periods
        period = FinancialPeriod(
            fiscal_year=ctx.end.year, period_start=ni.start if ni else None,
            period_end=ctx.end, filing_date=ni.filed if ni else None,
            form_type=ni.form if ni else None, is_annual=True, currency=ctx.currency,
            original_units=Units.UNITS,
            **{f: _to_financial_value(values[f][i], source_ref) for f in ALL_FIELDS})
        for field in ALL_FIELDS:
            if field not in ENGINE_DERIVED_FIELDS and period.get(field) is None:
                other = _other_currency_warning(field, ctx)
                if other:
                    warnings.append(other)
        missing = _missing_warning(period)
        if missing:
            warnings.append(missing)
        periods.append(period)

    if len(periods) < max_periods:
        warnings.append(f"Only {len(periods)} annual period(s) with core data were found "
                        f"(up to {max_periods} requested).")
    if company.reporting_framework is None:
        company = company.model_copy(update={"reporting_framework": "US GAAP"})
    return CompanyFinancials(company=company, source_type=SourceType.SEC_EDGAR,
                             periods=periods, warnings=warnings)
