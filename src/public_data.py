"""Owned by Person 2: end-to-end public data retrieval (SEC EDGAR -> PublicDataResult).

``fetch_public_financials`` takes a company the analyst has CONFIRMED and returns a
``PublicDataResult``. It never raises: every outcome becomes a ``DataAvailability`` status with
a plain-English message for the UI.

Status mapping (also in docs/data-sources.md):

=====================================================  ==========================
Outcome                                                Status
=====================================================  ==========================
invalid CIK (ValueError from pad_cik)                  API_UNAVAILABLE
SecConfigError (no SEC_CONTACT_EMAIL), any step        API_UNAVAILABLE
submissions: SecNotFoundError                          COMPANY_NOT_FOUND
any step: SecRateLimitError                            RATE_LIMITED
any step: SecUnavailableError / Malformed / other      API_UNAVAILABLE
facts: SecNotFoundError, no us-gaap, or no periods     NO_FINANCIAL_STATEMENTS
latest period lacks revenue/total_assets/curr. liab.   INSUFFICIENT_DATA
unexpected (non-SEC) exception, e.g. a bug             API_UNAVAILABLE (logged)
otherwise                                              AVAILABLE
=====================================================  ==========================

An outage or rate limit is NEVER reported as NO_FINANCIAL_STATEMENTS: it is a connection
problem, not proof that statements do not exist. Messages are fixed texts; exception text is
never copied into them (so the contact email can never leak into the UI).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src import config
from src.financial_normalizer import normalize_company_facts
from src.models import (
    FIELD_LABELS,
    CompanyFinancials,
    CompanyInfo,
    CompanyMatch,
    DataAvailability,
    PublicDataResult,
    SourceType,
)
from src.sec_client import (
    SecClient,
    SecClientError,
    SecConfigError,
    SecNotFoundError,
    SecRateLimitError,
    pad_cik,
)

logger = logging.getLogger(__name__)

FINANCIAL_SIC_MIN = 6000
FINANCIAL_SIC_MAX = 6799
CORE_FIELDS = ("revenue", "total_assets", "current_liabilities")

_ALTERNATIVES = "You can upload PDF financial statements or enter the figures manually instead."

MSG_INVALID_CIK = ("The selected company has an invalid SEC identifier (CIK), so its data could "
                   "not be requested. Please search again and select the company. "
                   + _ALTERNATIVES)
MSG_COMPANY_NOT_FOUND = ("The SEC (EDGAR) has no company record for this identifier. Please "
                         "check the company you selected. " + _ALTERNATIVES)
MSG_RATE_LIMITED = ("Connection problem: the SEC is temporarily limiting requests from this "
                    "app. This is NOT proof that the company's financial statements do not "
                    "exist. Please wait a few minutes and retry. " + _ALTERNATIVES)
MSG_UNAVAILABLE = ("Connection problem: the SEC (EDGAR) service could not be reached or "
                   "returned an unusable response. This is NOT proof that the company's "
                   "financial statements do not exist. Please retry in a few minutes. "
                   + _ALTERNATIVES)
MSG_UNEXPECTED = ("An unexpected problem occurred while processing the SEC data for this "
                  "company. This is NOT proof that its financial statements do not exist. "
                  "Please retry. " + _ALTERNATIVES)
MSG_NO_STATEMENTS = ("No annual US GAAP financial statements (10-K) for this company could be "
                     "found in the SEC structured data (XBRL).")


# --------------------------------------------------------------------------- helpers

def parse_sic(raw: Any) -> Optional[int]:
    """SIC code as int, or None if missing/blank/not a number."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def is_financial_sic(sic: Optional[int]) -> bool:
    """True for SIC 6000-6799 inclusive (banks, insurers, other financial)."""
    return sic is not None and FINANCIAL_SIC_MIN <= sic <= FINANCIAL_SIC_MAX


def _clean_str(raw: Any) -> Optional[str]:
    """Stripped string, or None when missing/blank."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _pick_ticker(match: CompanyMatch, submissions: dict) -> Optional[str]:
    """The searched ticker if the SEC lists it for this CIK, else the SEC's first ticker."""
    tickers = submissions.get("tickers")
    listed = [t for t in tickers if isinstance(t, str) and t.strip()] \
        if isinstance(tickers, list) else []
    if match.ticker and (not listed or match.ticker in listed):
        return match.ticker
    return listed[0] if listed else match.ticker


def build_company_info(match: CompanyMatch, cik: str, submissions: dict) -> CompanyInfo:
    """CompanyInfo from the SEC submissions JSON. Country is left None (never guessed)."""
    sic = parse_sic(submissions.get("sic"))
    return CompanyInfo(
        name=_clean_str(submissions.get("name")) or match.name,
        ticker=_pick_ticker(match, submissions),
        cik=cik,
        sic_code=str(sic) if sic is not None else None,
        sector=_clean_str(submissions.get("sicDescription")),
        country=None,
        reporting_framework=None,
        is_financial_institution=is_financial_sic(sic),
    )


def _error_result(exc: SecClientError) -> PublicDataResult:
    """Map an SEC client error (other than a facts 404) to a status. Never NO_FINANCIAL_STATEMENTS."""
    if isinstance(exc, SecConfigError):
        return PublicDataResult(status=DataAvailability.API_UNAVAILABLE,
                                message=SecConfigError.default_message)
    if isinstance(exc, SecRateLimitError):
        return PublicDataResult(status=DataAvailability.RATE_LIMITED, message=MSG_RATE_LIMITED)
    return PublicDataResult(status=DataAvailability.API_UNAVAILABLE, message=MSG_UNAVAILABLE)


def _with_fi_warning(financials: CompanyFinancials) -> CompanyFinancials:
    """Put FINANCIAL_INSTITUTION_MESSAGE first in warnings for financial institutions."""
    if not financials.company.is_financial_institution:
        return financials
    if config.FINANCIAL_INSTITUTION_MESSAGE in financials.warnings:
        return financials
    return financials.model_copy(
        update={"warnings": [config.FINANCIAL_INSTITUTION_MESSAGE, *financials.warnings]})


def _message(base: str, financials: CompanyFinancials, extra: Optional[str] = None) -> str:
    """Base message, plus the FI message and any extra detail."""
    parts = [base]
    if extra:
        parts.append(extra)
    if financials.company.is_financial_institution:
        parts.append(config.FINANCIAL_INSTITUTION_MESSAGE)
    return " ".join(parts)


def missing_core_fields(financials: CompanyFinancials) -> list[str]:
    """Core fields missing in the latest period (all of them if there is no period)."""
    latest = financials.latest()
    if latest is None:
        return list(CORE_FIELDS)
    return [f for f in CORE_FIELDS if latest.get(f) is None]


def _no_statements_result(company: CompanyInfo, warnings: list[str]) -> PublicDataResult:
    financials = _with_fi_warning(CompanyFinancials(
        company=company, source_type=SourceType.SEC_EDGAR, periods=[], warnings=warnings))
    reason = " ".join(w for w in warnings if w != config.FINANCIAL_INSTITUTION_MESSAGE)
    return PublicDataResult(status=DataAvailability.NO_FINANCIAL_STATEMENTS,
                            financials=financials,
                            message=_message(MSG_NO_STATEMENTS, financials, reason or None))


def _classify(financials: CompanyFinancials) -> PublicDataResult:
    """AVAILABLE / INSUFFICIENT_DATA / NO_FINANCIAL_STATEMENTS for normalized data."""
    if not financials.periods:
        return _no_statements_result(financials.company, list(financials.warnings))
    financials = _with_fi_warning(financials)
    years = ", ".join(f"FY{p.fiscal_year}" for p in financials.periods)
    found = (f"{len(financials.periods)} annual period(s) found in SEC EDGAR ({years}).")
    missing = missing_core_fields(financials)
    if missing:
        labels = ", ".join(FIELD_LABELS[f] for f in missing)
        return PublicDataResult(
            status=DataAvailability.INSUFFICIENT_DATA, financials=financials,
            message=_message(found, financials,
                             f"The latest period is missing core items: {labels}. You can "
                             "analyze anyway (missing items stay blank) or supplement the "
                             "data manually."))
    return PublicDataResult(status=DataAvailability.AVAILABLE, financials=financials,
                            message=_message(found, financials))


# --------------------------------------------------------------------------- public API

def fetch_public_financials(match: CompanyMatch,
                            client: Optional[SecClient] = None) -> PublicDataResult:
    """Fetch and normalise public financials for a confirmed company. Never raises.

    Args:
        match: the company the analyst confirmed (its CIK is the identity used).
        client: SecClient to use (a default one is created if None).

    Returns:
        PublicDataResult with a status (see module docstring), a plain-English message and,
        when anything was found, the CompanyFinancials (periods NEWEST FIRST).
    """
    try:
        return _fetch(match, client)
    except Exception:  # last resort: a bug must never crash the UI
        logger.exception("Unexpected error in fetch_public_financials")
        return PublicDataResult(status=DataAvailability.API_UNAVAILABLE,
                                message=MSG_UNEXPECTED)


def _fetch(match: CompanyMatch, client: Optional[SecClient]) -> PublicDataResult:
    try:
        cik = pad_cik(match.cik)
    except ValueError:
        return PublicDataResult(status=DataAvailability.API_UNAVAILABLE, message=MSG_INVALID_CIK)

    try:
        sec = client if client is not None else SecClient()
        submissions = sec.get_submissions(cik)
    except SecNotFoundError:
        return PublicDataResult(status=DataAvailability.COMPANY_NOT_FOUND,
                                message=MSG_COMPANY_NOT_FOUND)
    except SecClientError as exc:
        return _error_result(exc)

    company = build_company_info(match, cik, submissions)

    try:
        facts = sec.get_company_facts(cik)
    except SecNotFoundError:
        return _no_statements_result(
            company, ["The SEC has no structured (XBRL) company facts for this company."])
    except SecClientError as exc:
        return _error_result(exc)

    return _classify(normalize_company_facts(facts, company))
