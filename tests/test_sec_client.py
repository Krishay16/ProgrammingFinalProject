"""Offline tests for src/sec_client.py (Person 2).

All HTTP is faked; all JSON payloads below are tiny SYNTHETIC examples, not real SEC data.
Time is faked so rate-limit and cache-expiry tests run instantly.
"""
from __future__ import annotations

import json
import os

import pytest
import requests

from src import config
from src import sec_client as sc
from src.sec_client import (
    SecClient,
    SecClientError,
    SecConfigError,
    SecMalformedResponseError,
    SecNotFoundError,
    SecRateLimitError,
    SecUnavailableError,
    pad_cik,
)

EMAIL = "analyst@example.com"

# SYNTHETIC payloads (shape only, invented values)
TICKERS = {"0": {"cik_str": 1234567, "ticker": "SYNT", "title": "SYNTHETIC Corp"}}
SUBMISSIONS = {"cik": "1234567", "name": "SYNTHETIC Corp", "sicDescription": "Synthetic"}
FACTS = {"cik": 1234567, "entityName": "SYNTHETIC Corp", "facts": {"us-gaap": {}}}


# --------------------------------------------------------------------------- fakes

class FakeClock:
    """Shared fake time: sleep() advances both the monotonic and the wall clock."""

    def __init__(self, start: float = 1_000.0, wall_start: float = 1_700_000_000.0) -> None:
        self.t = start
        self.wall = wall_start
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    def now(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        self.wall += seconds


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = "",
                 bad_json: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text else (json.dumps(payload) if payload is not None else "")
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            return json.loads("{not json")  # raises json.JSONDecodeError (a ValueError)
        return self._payload


class FakeSession:
    """Records every get() call; returns queued responses or raises queued exceptions."""

    def __init__(self, outcomes, clock: FakeClock | None = None) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.clock = clock

    def get(self, url, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs,
                           "t": self.clock.clock() if self.clock else None})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def reset_shared_rate_limit():
    """The rate limit is shared across instances; isolate every test."""
    SecClient._reset_rate_limit_state()
    yield
    SecClient._reset_rate_limit_state()


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


def make_client(tmp_path, outcomes, fake_clock: FakeClock, **kwargs):
    session = FakeSession(outcomes, clock=fake_clock)
    params = dict(contact_email=EMAIL, cache_dir=str(tmp_path / "cache"),
                  session=session, clock=fake_clock.clock, now=fake_clock.now,
                  sleep=fake_clock.sleep)
    params.update(kwargs)
    return SecClient(**params), session


# --------------------------------------------------------------------------- config / headers

def test_headers_and_timeout_sent_on_every_call(tmp_path, fake_clock):
    client, session = make_client(tmp_path, [FakeResponse(200, TICKERS)], fake_clock)
    client.get_company_tickers()
    kwargs = session.calls[0]["kwargs"]
    assert kwargs["headers"]["User-Agent"] == f"{config.APP_NAME} {EMAIL}"
    assert EMAIL in kwargs["headers"]["User-Agent"]
    assert kwargs["headers"]["Accept-Encoding"] == "gzip, deflate"
    assert kwargs["timeout"] == 15.0


def test_missing_email_raises_config_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SEC_CONTACT_EMAIL", None)
    with pytest.raises(SecConfigError) as exc:
        SecClient(cache_dir=str(tmp_path), session=FakeSession([]))
    assert "SEC_CONTACT_EMAIL" in str(exc.value)


def test_email_falls_back_to_config(monkeypatch, tmp_path, fake_clock):
    monkeypatch.setattr(config, "SEC_CONTACT_EMAIL", "from-config@example.com")
    session = FakeSession([FakeResponse(200, TICKERS)])
    client = SecClient(cache_dir=str(tmp_path), session=session, clock=fake_clock.clock,
                       now=fake_clock.now, sleep=fake_clock.sleep)
    client.get_company_tickers()
    assert "from-config@example.com" in session.calls[0]["kwargs"]["headers"]["User-Agent"]


@pytest.mark.parametrize("bad_email", ["", "   ", "not-an-email"])
def test_blank_or_invalid_email_raises_config_error(monkeypatch, tmp_path, bad_email):
    monkeypatch.setattr(config, "SEC_CONTACT_EMAIL", None)
    with pytest.raises(SecConfigError) as exc:
        SecClient(contact_email=bad_email, cache_dir=str(tmp_path), session=FakeSession([]))
    assert "SEC_CONTACT_EMAIL" in str(exc.value)


# --------------------------------------------------------------------------- cache

def test_cache_hit_avoids_second_http_call(tmp_path, fake_clock):
    client, session = make_client(tmp_path, [FakeResponse(200, TICKERS)], fake_clock)
    first = client.get_company_tickers()
    second = client.get_company_tickers()
    assert first == second == TICKERS
    assert len(session.calls) == 1


def test_cache_shared_between_instances(tmp_path, fake_clock):
    client1, session1 = make_client(tmp_path, [FakeResponse(200, FACTS)], fake_clock)
    client1.get_company_facts("1234567")
    client2, session2 = make_client(tmp_path, [], fake_clock)
    assert client2.get_company_facts(1234567) == FACTS
    assert len(session2.calls) == 0


def test_expired_cache_triggers_new_call(tmp_path, fake_clock):
    client, session = make_client(
        tmp_path, [FakeResponse(200, TICKERS), FakeResponse(200, TICKERS)], fake_clock,
        cache_ttl_hours=24)
    client.get_company_tickers()
    fake_clock.wall += 24 * 3600 + 1
    client.get_company_tickers()
    assert len(session.calls) == 2


def test_corrupt_cache_file_is_a_miss(tmp_path, fake_clock):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "company_tickers.json").write_text("{corrupt", encoding="utf-8")
    client, session = make_client(tmp_path, [FakeResponse(200, TICKERS)], fake_clock)
    assert client.get_company_tickers() == TICKERS
    assert len(session.calls) == 1
    # and the corrupt file was replaced by a valid cache entry
    envelope = json.loads((cache_dir / "company_tickers.json").read_text(encoding="utf-8"))
    assert envelope["data"] == TICKERS


def test_cache_write_leaves_no_temp_files(tmp_path, fake_clock):
    client, _ = make_client(tmp_path, [FakeResponse(200, TICKERS)], fake_clock)
    client.get_company_tickers()
    assert os.listdir(tmp_path / "cache") == ["company_tickers.json"]


def test_error_responses_are_not_cached(tmp_path, fake_clock):
    client, session = make_client(
        tmp_path, [FakeResponse(404), FakeResponse(200, SUBMISSIONS)], fake_clock)
    with pytest.raises(SecNotFoundError):
        client.get_submissions("1234567")
    cache_dir = tmp_path / "cache"
    assert not cache_dir.exists() or os.listdir(cache_dir) == []
    assert client.get_submissions("1234567") == SUBMISSIONS
    assert len(session.calls) == 2


def test_malformed_response_is_not_cached(tmp_path, fake_clock):
    client, _ = make_client(tmp_path, [FakeResponse(200, {"oops": 1})], fake_clock)
    with pytest.raises(SecMalformedResponseError):
        client.get_submissions("1234567")
    cache_dir = tmp_path / "cache"
    assert not cache_dir.exists() or os.listdir(cache_dir) == []


# --------------------------------------------------------------------------- error mapping

def test_404_maps_to_not_found(tmp_path, fake_clock):
    client, session = make_client(tmp_path, [FakeResponse(404)], fake_clock)
    with pytest.raises(SecNotFoundError) as exc:
        client.get_submissions("1234567")
    assert len(session.calls) == 1  # never retried
    assert "does not necessarily mean the company does not exist" in str(exc.value)


def test_404_on_company_facts_says_no_structured_data(tmp_path, fake_clock):
    client, _ = make_client(tmp_path, [FakeResponse(404)], fake_clock)
    with pytest.raises(SecNotFoundError) as exc:
        client.get_company_facts("1234567")
    message = str(exc.value)
    assert "structured" in message
    assert "does not mean the company does not exist" in message


def test_429_maps_to_rate_limit(tmp_path, fake_clock):
    client, session = make_client(tmp_path, [FakeResponse(429)], fake_clock)
    with pytest.raises(SecRateLimitError):
        client.get_company_tickers()
    assert len(session.calls) == 1


@pytest.mark.parametrize("body", [
    "Your Request Originates from an Undeclared Automated Tool",
    "Request Rate Threshold Exceeded",
])
def test_403_rate_limit_body_maps_to_rate_limit(tmp_path, fake_clock, body):
    client, session = make_client(tmp_path, [FakeResponse(403, text=body)], fake_clock)
    with pytest.raises(SecRateLimitError):
        client.get_company_tickers()
    assert len(session.calls) == 1


@pytest.mark.parametrize("status,body", [(403, "Forbidden"), (400, "Bad request")])
def test_other_4xx_maps_to_base_error_without_retry(tmp_path, fake_clock, status, body):
    client, session = make_client(tmp_path, [FakeResponse(status, text=body)], fake_clock)
    with pytest.raises(SecClientError) as exc:
        client.get_company_tickers()
    assert type(exc.value) is SecClientError
    assert len(session.calls) == 1


def test_5xx_retries_once_then_raises_unavailable(tmp_path, fake_clock):
    client, session = make_client(tmp_path, [FakeResponse(500), FakeResponse(502)], fake_clock,
                                  retry_backoff_s=1.0)
    with pytest.raises(SecUnavailableError):
        client.get_company_tickers()
    assert len(session.calls) == 2
    assert 1.0 in fake_clock.sleeps


def test_5xx_then_success_returns_data(tmp_path, fake_clock):
    client, session = make_client(
        tmp_path, [FakeResponse(503), FakeResponse(200, TICKERS)], fake_clock)
    assert client.get_company_tickers() == TICKERS
    assert len(session.calls) == 2


@pytest.mark.parametrize("exc_type", [requests.exceptions.Timeout,
                                      requests.exceptions.ConnectionError])
def test_network_errors_retry_once_then_unavailable(tmp_path, fake_clock, exc_type):
    client, session = make_client(tmp_path, [exc_type("boom"), exc_type("boom")], fake_clock)
    with pytest.raises(SecUnavailableError):
        client.get_company_tickers()
    assert len(session.calls) == 2


def test_invalid_json_raises_malformed(tmp_path, fake_clock):
    client, _ = make_client(tmp_path, [FakeResponse(200, text="<html>", bad_json=True)],
                            fake_clock)
    with pytest.raises(SecMalformedResponseError):
        client.get_company_tickers()


@pytest.mark.parametrize("method,args,payload", [
    ("get_company_tickers", (), {}),                                  # empty ticker dict
    ("get_company_tickers", (), {"0": {"ticker": "X"}}),              # missing keys
    ("get_company_tickers", (), ["not", "a", "dict"]),
    ("get_submissions", ("1234567",), {"cik": "1234567"}),            # no name
    ("get_company_facts", ("1234567",), {"entityName": "X"}),         # no facts
    ("get_company_facts", ("1234567",), {"facts": []}),               # facts not a dict
])
def test_unexpected_structure_raises_malformed(tmp_path, fake_clock, method, args, payload):
    client, _ = make_client(tmp_path, [FakeResponse(200, payload)], fake_clock)
    with pytest.raises(SecMalformedResponseError):
        getattr(client, method)(*args)


def test_company_facts_with_empty_facts_is_valid(tmp_path, fake_clock):
    payload = {"cik": 1234567, "entityName": "SYNTHETIC Corp", "facts": {}}
    client, _ = make_client(tmp_path, [FakeResponse(200, payload)], fake_clock)
    assert client.get_company_facts("1234567") == payload


def test_email_never_in_exception_messages(tmp_path, fake_clock):
    outcomes = [FakeResponse(404), FakeResponse(429), FakeResponse(403, text="Forbidden"),
                FakeResponse(500), FakeResponse(500), FakeResponse(200, text="x", bad_json=True),
                FakeResponse(418)]
    client, _ = make_client(tmp_path, outcomes, fake_clock, cache_ttl_hours=0)
    for _ in range(6):
        with pytest.raises(SecClientError) as exc:
            client.get_company_tickers()
        assert EMAIL not in str(exc.value)


# --------------------------------------------------------------------------- rate limit

def test_two_calls_spaced_by_min_interval(tmp_path, fake_clock):
    client, session = make_client(
        tmp_path, [FakeResponse(200, TICKERS), FakeResponse(200, TICKERS)], fake_clock,
        cache_ttl_hours=0, min_interval_s=0.15)
    client.get_company_tickers()
    client.get_company_tickers()
    t1, t2 = session.calls[0]["t"], session.calls[1]["t"]
    assert t2 - t1 >= 0.15 - 1e-9
    assert fake_clock.sleeps and fake_clock.sleeps[0] == pytest.approx(0.15)


def test_rate_limit_shared_across_instances(tmp_path, fake_clock):
    client1, session1 = make_client(tmp_path, [FakeResponse(200, TICKERS)], fake_clock,
                                    cache_ttl_hours=0, min_interval_s=0.15)
    client2, session2 = make_client(tmp_path, [FakeResponse(200, TICKERS)], fake_clock,
                                    cache_ttl_hours=0, min_interval_s=0.15)
    client1.get_company_tickers()
    client2.get_company_tickers()
    t1, t2 = session1.calls[0]["t"], session2.calls[0]["t"]
    assert t2 - t1 >= 0.15 - 1e-9


def test_no_sleep_when_interval_already_elapsed(tmp_path, fake_clock):
    client, _ = make_client(
        tmp_path, [FakeResponse(200, TICKERS), FakeResponse(200, TICKERS)], fake_clock,
        cache_ttl_hours=0, min_interval_s=0.15)
    client.get_company_tickers()
    fake_clock.t += 5
    client.get_company_tickers()
    assert fake_clock.sleeps == []


# --------------------------------------------------------------------------- URLs / pad_cik

def test_urls_use_padded_cik(tmp_path, fake_clock):
    client, session = make_client(
        tmp_path, [FakeResponse(200, SUBMISSIONS), FakeResponse(200, FACTS)], fake_clock)
    client.get_submissions(789019)
    client.get_company_facts("CIK789019")
    assert session.calls[0]["url"] == "https://data.sec.gov/submissions/CIK0000789019.json"
    assert session.calls[1]["url"] == (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json")
    assert session.calls[0]["url"] == sc.SUBMISSIONS_URL.format(cik="0000789019")


@pytest.mark.parametrize("raw,expected", [
    (789019, "0000789019"),
    ("789019", "0000789019"),
    ("0000789019", "0000789019"),
    (" CIK0000789019 ", "0000789019"),
    ("cik320193", "0000320193"),
    (0, "0000000000"),
])
def test_pad_cik_valid(raw, expected):
    assert pad_cik(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "abc", "12a4", "12345678901", -5, None, 1.5, True])
def test_pad_cik_invalid_raises_value_error(raw):
    with pytest.raises(ValueError):
        pad_cik(raw)


def test_invalid_cik_raises_before_any_http(tmp_path, fake_clock):
    client, session = make_client(tmp_path, [], fake_clock)
    with pytest.raises(ValueError):
        client.get_company_facts("not-a-cik")
    assert session.calls == []


# --------------------------------------------------------------------------- live (opt-in)

@pytest.mark.live
def test_live_company_tickers(tmp_path):
    """Real call to the SEC. Run with: pytest -m live (needs SEC_CONTACT_EMAIL in .env)."""
    if not config.SEC_CONTACT_EMAIL:
        pytest.skip("SEC_CONTACT_EMAIL not set")
    client = SecClient(cache_dir=str(tmp_path))
    data = client.get_company_tickers()
    assert len(data) > 1000
