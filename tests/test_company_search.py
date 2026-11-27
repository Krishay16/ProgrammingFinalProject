"""Offline tests for src/company_search.py (Person 2).

The ticker fixture tests/fixtures/sec/company_tickers_sample.json is a REAL subset of the SEC
company_tickers.json file, cut by scripts/build_sec_fixtures.py (rows copied unchanged).
No network: a fake client returns the fixture.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import company_search as cs
from src.company_search import search_companies
from src.sec_client import (
    SecClientError,
    SecConfigError,
    SecRateLimitError,
    SecUnavailableError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sec" / "company_tickers_sample.json"


class FakeClient:
    """Stands in for SecClient; returns the real ticker subset or raises an error."""

    def __init__(self, data: dict | None = None, error: Exception | None = None) -> None:
        self.data = data
        self.error = error
        self.calls = 0

    def get_company_tickers(self) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.data


@pytest.fixture(scope="module")
def tickers() -> dict:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def client(tickers) -> FakeClient:
    return FakeClient(tickers)


def _tickers(matches) -> list:
    return [m.ticker for m in matches]


# --------------------------------------------------------------------------- normalization

@pytest.mark.parametrize("raw, expected", [
    ("Coca-Cola", "coca cola"),
    ("THE COCA-COLA COMPANY", "coca cola"),
    ("COCA COLA CO", "coca cola"),
    ("Apple Inc.", "apple"),
    ("Tesla, Inc.", "tesla"),
    ("McDonald's Corp", "mcdonalds"),
    ("BANK OF EXAMPLE CORP /DE/", "bank of example"),
    ("Nestlé Holdings Ltd", "nestle"),
    ("  Inc  ", ""),
])
def test_normalize_name(raw, expected):
    assert cs._normalize_name(raw) == expected


def test_normalize_name_keeps_title_that_is_only_suffixes():
    assert cs._normalize_name("Holdings Inc", keep_if_empty=True) == "holdings inc"


# --------------------------------------------------------------------------- tiers

def test_exact_ticker_ranks_first(client):
    matches = search_companies("AAPL", client=client)
    assert matches[0].ticker == "AAPL"
    assert matches[0].match_score == cs.SCORE_TICKER


def test_ticker_is_case_insensitive(client):
    assert search_companies("msft", client=client)[0].ticker == "MSFT"


@pytest.mark.parametrize("query", ["BRK.B", "brk-b", "Brk.b"])
def test_ticker_dot_equals_dash(client, query):
    first = search_companies(query, client=client)[0]
    assert first.ticker == "BRK-B"
    assert first.cik == "0001067983"


@pytest.mark.parametrize("query", ["Apple", "apple inc", "APPLE INC.", "The Apple Company"])
def test_exact_name_ignores_case_and_suffixes(client, query):
    first = search_companies(query, client=client)[0]
    assert first.ticker == "AAPL"
    assert first.match_score == cs.SCORE_EXACT_NAME


@pytest.mark.parametrize("query", ["Coca-Cola", "coca cola", "The Coca-Cola Company",
                                   "COCA COLA CO", "cocacola"])
def test_coca_cola_variations(client, query):
    first = search_companies(query, client=client)[0]
    assert first.ticker == "KO"
    assert first.cik == "0000021344"


def test_similar_names_are_all_returned_and_disambiguated(client):
    matches = search_companies("Coca-Cola", client=client)
    assert _tickers(matches)[0] == "KO"
    # The other real Coca-Cola entities come after, as starts-with matches.
    assert {"COKE", "CCEP", "KOF"} <= set(_tickers(matches))
    assert all(m.match_score == cs.SCORE_STARTS_WITH for m in matches[1:])


def test_exact_name_beats_starts_with(client):
    matches = search_companies("Apple", client=client)
    assert _tickers(matches)[:2] == ["AAPL", "APLE"]
    assert matches[1].match_score == cs.SCORE_STARTS_WITH


def test_partial_name_starts_with(client):
    matches = search_companies("micro", client=client)
    assert matches[0].ticker == "MSFT"
    assert matches[0].match_score == cs.SCORE_STARTS_WITH


def test_contains_whole_word(client):
    matches = search_companies("Hospitality", client=client)
    assert matches[0].ticker == "APLE"
    assert matches[0].match_score == cs.SCORE_CONTAINS


def test_starts_with_ranks_above_contains(client):
    rows = {"0": {"cik_str": 1, "ticker": "AAA", "title": "SYNTHETIC Beta Foods Inc"},
            "1": {"cik_str": 2, "ticker": "BBB", "title": "Beta Systems Corp"}}
    matches = search_companies("beta", client=FakeClient(rows))
    assert _tickers(matches) == ["BBB", "AAA"]
    assert [m.match_score for m in matches] == [cs.SCORE_STARTS_WITH, cs.SCORE_CONTAINS]


def test_fuzzy_finds_typo(client):
    matches = search_companies("Microsfot", client=client)
    assert matches[0].ticker == "MSFT"
    assert 0 < matches[0].match_score <= cs.FUZZY_WEIGHT


def test_fuzzy_not_run_when_earlier_tiers_fill_limit(client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("fuzzy step should not run")
    monkeypatch.setattr(cs, "_fuzzy_score", boom)
    matches = search_companies("coca", client=client, limit=2)
    assert len(matches) == 2


def test_fuzzy_runs_when_earlier_tiers_find_too_few(client, monkeypatch):
    calls = []
    original = cs._fuzzy_score

    def spy(row, q_key):
        calls.append(row.cik)
        return original(row, q_key)
    monkeypatch.setattr(cs, "_fuzzy_score", spy)
    search_companies("tesla", client=client, limit=10)
    assert calls


def test_limit_is_respected(client):
    assert len(search_companies("coca", client=client, limit=2)) == 2
    assert search_companies("coca", client=client, limit=0) == []


def test_deduplicates_by_cik_keeping_first_listed_ticker(client):
    matches = search_companies("Alphabet", client=client)
    alphabet = [m for m in matches if m.cik == "0001652044"]
    assert len(alphabet) == 1
    assert alphabet[0].ticker == "GOOGL"  # first row of that CIK in the SEC file
    berkshire = [m for m in search_companies("berkshire", client=client)
                 if m.cik == "0001067983"]
    assert len(berkshire) == 1


def test_cik_is_ten_digits(client):
    for m in search_companies("a", client=client) + search_companies("coca", client=client):
        assert len(m.cik) == 10 and m.cik.isdigit()


def test_name_is_original_sec_title(client):
    assert search_companies("TSLA", client=client)[0].name == "Tesla, Inc."


# --------------------------------------------------------------------------- empty / odd input

@pytest.mark.parametrize("query", ["", "   ", "Inc", "The", "the inc.", "--", "...", "Corp & Co"])
def test_meaningless_queries_return_empty_without_calling_sec(query):
    fake = FakeClient({})
    assert search_companies(query, client=fake) == []
    assert fake.calls == 0


def test_one_character_query_skips_partial_and_fuzzy(client):
    # "a" would start-with-match Apple, Alphabet and Amazon if partial matching ran.
    assert search_companies("a", client=client) == []


def test_non_string_query_returns_empty(client):
    assert search_companies(None, client=client) == []  # type: ignore[arg-type]


@pytest.mark.parametrize("query", ["🍎🍎", "x" * 5000, "%$#@!", "SELECT * FROM", "\x00null"])
def test_odd_queries_never_raise(client, query):
    assert isinstance(search_companies(query, client=client), list)


def test_bad_rows_are_skipped():
    rows = {"0": {"cik_str": "not-a-cik", "ticker": "BAD", "title": "SYNTHETIC Bad Row"},
            "1": {"cik_str": 42, "ticker": "GOOD", "title": "SYNTHETIC Good Row"},
            "2": "not a dict"}
    matches = search_companies("synthetic", client=FakeClient(rows))
    assert [m.ticker for m in matches] == ["GOOD"]
    assert matches[0].cik == "0000000042"


# --------------------------------------------------------------------------- SEC errors propagate

@pytest.mark.parametrize("error", [SecUnavailableError(), SecRateLimitError(),
                                   SecConfigError(), SecClientError()])
def test_sec_errors_propagate(error):
    with pytest.raises(type(error)):
        search_companies("Apple", client=FakeClient(error=error))


def test_missing_contact_email_propagates_config_error(monkeypatch):
    from src import config
    monkeypatch.setattr(config, "SEC_CONTACT_EMAIL", None)
    with pytest.raises(SecConfigError):
        search_companies("Apple")
