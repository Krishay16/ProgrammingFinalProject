"""Offline tests for src/public_data.py (Person 2).

No network: a FakeClient returns fixtures or raises SEC client errors.
* Company facts: tests/fixtures/sec/microsoft_companyfacts_trimmed_fixture.json is REAL SEC data
  (trimmed, values unchanged); variants below are derived from it by deleting tags.
* Submissions: SYNTHETIC dicts written here (invented, minimal; only the keys the code reads).
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

import pytest

from src import config
from src import public_data as pd_mod
from src.models import (
    CompanyFinancials,
    CompanyInfo,
    CompanyMatch,
    DataAvailability,
    FinancialPeriod,
    FinancialValue,
    SourceType,
)
from src.public_data import fetch_public_financials, is_financial_sic, parse_sic
from src.sec_client import (
    SecClientError,
    SecConfigError,
    SecMalformedResponseError,
    SecNotFoundError,
    SecRateLimitError,
    SecUnavailableError,
)

SEC_DIR = Path(__file__).parent / "fixtures" / "sec"
MSFT_CIK = "0000789019"
FAKE_EMAIL = "secret-contact@example.com"

OUTAGE_ERRORS = [SecRateLimitError(), SecUnavailableError(), SecMalformedResponseError(),
                 SecClientError(), SecConfigError()]


def _submissions(sic: object = "7372", **extra) -> dict:
    """SYNTHETIC submissions JSON (only the keys public_data reads)."""
    data = {"cik": "789019", "name": "MICROSOFT CORP", "tickers": ["MSFT"],
            "sicDescription": "SYNTHETIC sector description", "fiscalYearEnd": "0630"}
    if sic is not None:
        data["sic"] = sic
    data.update(extra)
    return data


@pytest.fixture(scope="module")
def msft_facts() -> dict:
    with open(SEC_DIR / "microsoft_companyfacts_trimmed_fixture.json", encoding="utf-8") as fh:
        return json.load(fh)


class FakeClient:
    """Stands in for SecClient: each method returns its data or raises its error."""

    def __init__(self, submissions=None, facts=None, sub_error=None, facts_error=None):
        self.submissions = submissions if submissions is not None else _submissions()
        self.facts = facts
        self.sub_error = sub_error
        self.facts_error = facts_error
        self.calls: list[str] = []

    def get_submissions(self, cik: str) -> dict:
        self.calls.append(f"submissions:{cik}")
        if self.sub_error is not None:
            raise self.sub_error
        return self.submissions

    def get_company_facts(self, cik: str) -> dict:
        self.calls.append(f"facts:{cik}")
        if self.facts_error is not None:
            raise self.facts_error
        return self.facts


MATCH = CompanyMatch(name="MICROSOFT CORP", ticker="MSFT", cik=MSFT_CIK, match_score=1.0)


# --------------------------------------------------------------------------- AVAILABLE

def test_available_with_real_msft_facts(msft_facts):
    client = FakeClient(facts=msft_facts)
    r = fetch_public_financials(MATCH, client=client)
    assert r.status == DataAvailability.AVAILABLE
    f = r.financials
    assert f is not None and len(f.periods) == 3
    assert [p.fiscal_year for p in f.periods] == sorted((p.fiscal_year for p in f.periods),
                                                        reverse=True)
    c = f.company
    assert c.name == "MICROSOFT CORP" and c.ticker == "MSFT" and c.cik == MSFT_CIK
    assert c.sic_code == "7372" and c.sector == "SYNTHETIC sector description"
    assert c.reporting_framework == "US GAAP"
    assert c.country is None
    assert c.is_financial_institution is False
    assert config.FINANCIAL_INSTITUTION_MESSAGE not in f.warnings
    assert "annual period" in r.message
    assert client.calls == [f"submissions:{MSFT_CIK}", f"facts:{MSFT_CIK}"]


def test_official_name_from_submissions_overrides_search_title(msft_facts):
    match = CompanyMatch(name="Microsoft (typed)", ticker="MSFT", cik="789019")
    r = fetch_public_financials(match, client=FakeClient(facts=msft_facts))
    assert r.financials.company.name == "MICROSOFT CORP"
    assert r.financials.company.cik == MSFT_CIK  # padded


def test_blank_submissions_name_falls_back_to_match_name(msft_facts):
    r = fetch_public_financials(MATCH, client=FakeClient(
        submissions=_submissions(name="  "), facts=msft_facts))
    assert r.financials.company.name == "MICROSOFT CORP"


def test_ticker_not_listed_uses_sec_first_ticker(msft_facts):
    match = CompanyMatch(name="X", ticker="OLD", cik=MSFT_CIK)
    r = fetch_public_financials(match, client=FakeClient(facts=msft_facts))
    assert r.financials.company.ticker == "MSFT"


# --------------------------------------------------------------------------- INSUFFICIENT_DATA

def _without(facts: dict, *tags: str) -> dict:
    out = copy.deepcopy(facts)
    for tag in tags:
        out["facts"]["us-gaap"].pop(tag, None)
    return out


def test_insufficient_when_current_liabilities_missing(msft_facts):
    facts = _without(msft_facts, "LiabilitiesCurrent")
    r = fetch_public_financials(MATCH, client=FakeClient(facts=facts))
    assert r.status == DataAvailability.INSUFFICIENT_DATA
    assert r.financials is not None and r.financials.periods  # still returns what was found
    assert r.financials.latest().get("current_liabilities") is None
    assert "Current liabilities" in r.message


def test_insufficient_when_revenue_missing(monkeypatch):
    period = FinancialPeriod(fiscal_year=2024, total_assets=FinancialValue(value=10.0),
                             current_liabilities=FinancialValue(value=5.0))
    fake = CompanyFinancials(company=CompanyInfo(name="SYNTHETIC Co", cik=MSFT_CIK),
                             source_type=SourceType.SEC_EDGAR, periods=[period])
    monkeypatch.setattr(pd_mod, "normalize_company_facts", lambda facts, company: fake)
    r = fetch_public_financials(MATCH, client=FakeClient(facts={"facts": {}}))
    assert r.status == DataAvailability.INSUFFICIENT_DATA
    assert pd_mod.missing_core_fields(r.financials) == ["revenue"]
    assert "Revenue" in r.message


# --------------------------------------------------------------------------- NO_FINANCIAL_STATEMENTS

def test_facts_404_is_no_financial_statements():
    r = fetch_public_financials(MATCH, client=FakeClient(facts_error=SecNotFoundError()))
    assert r.status == DataAvailability.NO_FINANCIAL_STATEMENTS
    assert r.financials is not None and r.financials.periods == []
    assert r.financials.company.name == "MICROSOFT CORP"


def test_ifrs_only_facts_is_no_financial_statements_with_normalizer_reason():
    facts = {"cik": 910631, "facts": {"ifrs-full": {"Revenue": {}}}}  # SYNTHETIC shape
    r = fetch_public_financials(MATCH, client=FakeClient(facts=facts))
    assert r.status == DataAvailability.NO_FINANCIAL_STATEMENTS
    assert any("IFRS" in w for w in r.financials.warnings)
    assert "IFRS" in r.message


@pytest.mark.parametrize("facts", [{"facts": {}}, {"facts": {"us-gaap": {}}}])
def test_empty_facts_is_no_financial_statements(facts):
    r = fetch_public_financials(MATCH, client=FakeClient(facts=facts))
    assert r.status == DataAvailability.NO_FINANCIAL_STATEMENTS
    assert r.financials.warnings


def test_normalizer_returning_no_periods_is_no_financial_statements(msft_facts):
    # Without NetIncomeLoss no period qualifies (normalizer rule 5) -> periods == [].
    facts = _without(msft_facts, "NetIncomeLoss")
    r = fetch_public_financials(MATCH, client=FakeClient(facts=facts))
    assert r.status == DataAvailability.NO_FINANCIAL_STATEMENTS
    assert r.financials.periods == []
    assert r.financials.warnings
    assert r.financials.warnings[-1] in r.message


# --------------------------------------------------------------------------- COMPANY_NOT_FOUND

def test_submissions_404_is_company_not_found():
    client = FakeClient(sub_error=SecNotFoundError())
    r = fetch_public_financials(MATCH, client=client)
    assert r.status == DataAvailability.COMPANY_NOT_FOUND
    assert r.financials is None
    assert client.calls == [f"submissions:{MSFT_CIK}"]  # facts not requested


# --------------------------------------------------------------------------- outages

@pytest.mark.parametrize("where", ["submissions", "facts"])
@pytest.mark.parametrize("error, expected", [
    (SecRateLimitError(), DataAvailability.RATE_LIMITED),
    (SecUnavailableError(), DataAvailability.API_UNAVAILABLE),
    (SecMalformedResponseError(), DataAvailability.API_UNAVAILABLE),
    (SecClientError(), DataAvailability.API_UNAVAILABLE),
    (SecConfigError(), DataAvailability.API_UNAVAILABLE),
])
def test_outage_mapping(where, error, expected, msft_facts):
    kwargs = {"sub_error": error} if where == "submissions" else {"facts_error": error}
    r = fetch_public_financials(MATCH, client=FakeClient(facts=msft_facts, **kwargs))
    assert r.status == expected
    assert r.financials is None


@pytest.mark.parametrize("where", ["submissions", "facts"])
@pytest.mark.parametrize("error", OUTAGE_ERRORS)
def test_outage_and_rate_limit_are_never_no_financial_statements(where, error, msft_facts):
    kwargs = {"sub_error": error} if where == "submissions" else {"facts_error": error}
    r = fetch_public_financials(MATCH, client=FakeClient(facts=msft_facts, **kwargs))
    assert r.status not in (DataAvailability.NO_FINANCIAL_STATEMENTS,
                            DataAvailability.COMPANY_NOT_FOUND)
    assert config.NO_DATA_MESSAGE not in r.message


@pytest.mark.parametrize("error", [SecRateLimitError(), SecUnavailableError(),
                                   SecMalformedResponseError()])
def test_outage_message_says_connection_problem_not_proof(error):
    r = fetch_public_financials(MATCH, client=FakeClient(sub_error=error))
    assert "Connection problem" in r.message
    assert "NOT proof" in r.message
    assert "PDF" in r.message and "manually" in r.message


def test_config_error_from_client_constructor(monkeypatch):
    monkeypatch.setattr(config, "SEC_CONTACT_EMAIL", None)
    r = fetch_public_financials(MATCH)  # default SecClient() raises SecConfigError
    assert r.status == DataAvailability.API_UNAVAILABLE
    assert "SEC_CONTACT_EMAIL" in r.message


def test_config_error_from_call():
    r = fetch_public_financials(MATCH, client=FakeClient(sub_error=SecConfigError()))
    assert r.status == DataAvailability.API_UNAVAILABLE
    assert "SEC_CONTACT_EMAIL" in r.message


def test_exception_text_with_email_never_reaches_message():
    err = SecUnavailableError(f"failed for {FAKE_EMAIL}")
    r = fetch_public_financials(MATCH, client=FakeClient(sub_error=err))
    assert FAKE_EMAIL not in r.message


# --------------------------------------------------------------------------- odd inputs / bugs

@pytest.mark.parametrize("cik", ["abc", "12345678901", "", "-5"])
def test_invalid_cik_from_pad_cik_never_raises(cik):
    match = CompanyMatch.model_construct(name="X", ticker=None, cik=cik, match_score=0.0)
    client = FakeClient()
    r = fetch_public_financials(match, client=client)
    assert r.status == DataAvailability.API_UNAVAILABLE
    assert client.calls == []
    assert r.message


def test_unexpected_exception_is_logged_and_not_raised(monkeypatch, caplog):
    def boom(facts, company):
        raise RuntimeError("normalizer bug")
    monkeypatch.setattr(pd_mod, "normalize_company_facts", boom)
    with caplog.at_level(logging.ERROR, logger="src.public_data"):
        r = fetch_public_financials(MATCH, client=FakeClient(facts={"facts": {}}))
    assert r.status == DataAvailability.API_UNAVAILABLE
    assert "normalizer bug" not in r.message
    records = [rec for rec in caplog.records if rec.name == "src.public_data"]
    assert records and records[0].exc_info is not None  # full traceback logged


def test_every_status_has_a_message(msft_facts):
    clients = [FakeClient(facts=msft_facts), FakeClient(sub_error=SecNotFoundError()),
               FakeClient(facts_error=SecNotFoundError()),
               FakeClient(facts=_without(msft_facts, "LiabilitiesCurrent"))]
    clients += [FakeClient(sub_error=e) for e in OUTAGE_ERRORS]
    for client in clients:
        assert fetch_public_financials(MATCH, client=client).message.strip()


# --------------------------------------------------------------------------- financial institutions

@pytest.mark.parametrize("sic, expected", [
    ("6000", True), ("6799", True), ("6022", True), (6311, True),
    ("5999", False), ("7000", False), ("6800", False), ("", False), ("  ", False),
    (None, False), ("abc", False),
])
def test_sic_detection(sic, expected):
    assert is_financial_sic(parse_sic(sic)) is expected


@pytest.mark.parametrize("sic", ["6000", "6799"])
def test_financial_institution_flag_and_message(sic, msft_facts):
    r = fetch_public_financials(MATCH, client=FakeClient(submissions=_submissions(sic=sic),
                                                         facts=msft_facts))
    c = r.financials.company
    assert c.is_financial_institution is True
    assert r.financials.warnings[0] == config.FINANCIAL_INSTITUTION_MESSAGE
    assert config.FINANCIAL_INSTITUTION_MESSAGE in r.message


@pytest.mark.parametrize("sic", ["5999", "7000", "", None])
def test_not_financial_institution(sic, msft_facts):
    r = fetch_public_financials(MATCH, client=FakeClient(submissions=_submissions(sic=sic),
                                                         facts=msft_facts))
    assert r.financials.company.is_financial_institution is False
    assert config.FINANCIAL_INSTITUTION_MESSAGE not in r.financials.warnings
    assert r.status == DataAvailability.AVAILABLE


def test_financial_institution_without_statements_still_flagged():
    r = fetch_public_financials(MATCH, client=FakeClient(
        submissions=_submissions(sic="6331"), facts_error=SecNotFoundError()))
    assert r.status == DataAvailability.NO_FINANCIAL_STATEMENTS
    assert r.financials.company.is_financial_institution is True
    assert config.FINANCIAL_INSTITUTION_MESSAGE in r.financials.warnings
