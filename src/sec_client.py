"""Owned by Person 2: SEC EDGAR HTTP client (headers, cache, rate limit, errors).

A small, polite and testable client for three free, official SEC EDGAR endpoints:

- ticker list:    https://www.sec.gov/files/company_tickers.json
- submissions:    https://data.sec.gov/submissions/CIK##########.json
- company facts:  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

Access rules we follow (https://www.sec.gov/search-filings/edgar-application-programming-interfaces):
every request identifies the app and a contact email in the User-Agent, requests are spaced
by at least ``min_interval_s`` (0.15 s by default, i.e. at most ~6.7 requests per second,
well under the SEC's 10 per second), and successful responses are cached on disk.

Design decisions for gaps in the original spec (agreed with the team member who owns this file):

* Error mapping:
    - 404 -> SecNotFoundError (message does NOT claim the company does not exist).
    - 429, or 403 whose body mentions "rate", "limit" or "undeclared automated tool"
      -> SecRateLimitError.
    - Any other 403 and any other unexpected 4xx -> SecClientError (the base class).
    - Timeouts, connection errors and 5xx -> SecUnavailableError.
    - Invalid JSON or unexpected structure -> SecMalformedResponseError.
* Retries: exactly ONE retry, after a short backoff, and only for timeouts, connection
  errors and 5xx. 4xx responses are never retried.
* Time is injectable (``clock`` for rate limiting, ``now`` for cache age, ``sleep``) so tests
  run instantly without real sleeping.
* The rate limit is SHARED across all SecClient instances (class-level timestamp protected by
  a threading.Lock), because Streamlit may build a new client on every rerun.
* Headers and timeout are passed explicitly on every ``session.get`` call, so they are sent
  even when a session is injected.
* Cache files are written atomically (temp file + os.replace). A corrupt, unreadable or
  wrongly structured cache file is treated as a cache miss, never a crash. Error responses
  are never cached.
* Structure checks: tickers = non-empty dict whose entries all have cik_str/ticker/title;
  submissions has "cik" and "name"; companyfacts has "facts" that is a dict (an EMPTY dict
  is valid: a real company may have no XBRL data).
* The contact email must be non-blank and contain "@" (no stricter validation). It is never
  put into exception messages or logs.
* ``pad_cik`` raises ValueError for invalid input (a programming/input error, not an SEC
  response); callers should catch it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from src import config

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_RATE_LIMIT_HINTS = ("rate", "limit", "undeclared automated tool")


# --------------------------------------------------------------------------- exceptions

class SecClientError(Exception):
    """Base class for all SEC client errors. Each subclass has a plain-English UI message."""

    default_message = ("Something went wrong while contacting the SEC (EDGAR). "
                       "Please try again, or provide the figures via PDF upload or manual entry.")

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or self.default_message)

    @property
    def message(self) -> str:
        """The plain-English message for the UI."""
        return str(self)


class SecConfigError(SecClientError):
    """Missing configuration, e.g. SEC_CONTACT_EMAIL not set."""

    default_message = ("The SEC requires every request to identify who is making it. Please set "
                       "SEC_CONTACT_EMAIL in your .env file to a valid contact email address "
                       "(see .env.example), then restart the app.")


class SecNotFoundError(SecClientError):
    """The requested resource does not exist (HTTP 404)."""

    default_message = ("The requested record was not found at the SEC (EDGAR). This does not "
                       "necessarily mean the company does not exist.")


class SecRateLimitError(SecClientError):
    """The SEC rate-limited or blocked the request."""

    default_message = ("The SEC is temporarily limiting requests from this app. Please wait a "
                       "few minutes and try again. This does not mean the company has no data.")


class SecUnavailableError(SecClientError):
    """Timeout, connection problem or 5xx from the SEC."""

    default_message = ("The SEC (EDGAR) service could not be reached or is temporarily "
                       "unavailable. This does not mean the company has no data. Please try "
                       "again in a few minutes.")


class SecMalformedResponseError(SecClientError):
    """The SEC returned something that is not the expected JSON."""

    default_message = ("The SEC returned data in an unexpected format, so it could not be used. "
                       "Please try again later, or provide the figures via PDF upload or "
                       "manual entry.")


FACTS_NOT_FOUND_MESSAGE = ("No company facts were found at the SEC for this company. This "
                           "usually means no structured (XBRL) financial data is available "
                           "there; it does not mean the company does not exist.")


# --------------------------------------------------------------------------- helpers

def pad_cik(cik: str | int) -> str:
    """Return a CIK as a 10-digit zero-padded string, e.g. 789019 -> "0000789019".

    Accepts an int, a digit string, optional surrounding whitespace and an optional
    "CIK" prefix (case-insensitive).

    Raises:
        ValueError: if the input is empty, negative, not made of digits, longer than
            10 digits, or not a str/int (bool is rejected). Callers such as
            company_search and public_data should catch it.
    """
    if isinstance(cik, bool) or not isinstance(cik, (str, int)):
        raise ValueError(f"CIK must be a string or integer, got {type(cik).__name__}")
    if isinstance(cik, int):
        if cik < 0:
            raise ValueError("CIK cannot be negative")
        text = str(cik)
    else:
        text = cik.strip()
        if text.upper().startswith("CIK"):
            text = text[3:].strip()
    if not re.fullmatch(r"[0-9]{1,10}", text):
        raise ValueError(f"Invalid CIK {cik!r}: expected 1 to 10 digits")
    return text.zfill(10)


def _is_valid_tickers(data: Any) -> bool:
    """company_tickers.json: non-empty dict of entries with cik_str, ticker and title."""
    if not isinstance(data, dict) or not data:
        return False
    return all(isinstance(entry, dict) and {"cik_str", "ticker", "title"} <= entry.keys()
               for entry in data.values())


def _is_valid_submissions(data: Any) -> bool:
    """Submissions JSON must be a dict with "cik" and "name"."""
    return isinstance(data, dict) and "cik" in data and "name" in data


def _is_valid_company_facts(data: Any) -> bool:
    """Companyfacts JSON must have a "facts" dict (an empty dict is valid)."""
    return isinstance(data, dict) and isinstance(data.get("facts"), dict)


# --------------------------------------------------------------------------- client

class SecClient:
    """Polite SEC EDGAR client. Methods return parsed JSON dicts.

    Args:
        contact_email: email for the User-Agent; defaults to config.SEC_CONTACT_EMAIL.
        cache_dir: folder for cached JSON responses.
        cache_ttl_hours: cache entries younger than this are reused (0 disables reuse).
        min_interval_s: minimum spacing between ANY two requests, across all instances.
        session: optional requests.Session (or a fake with the same .get) for tests.
        clock: monotonic clock used for rate limiting.
        now: wall clock (epoch seconds) used for cache age.
        sleep: sleep function.
        timeout_s: per-request timeout in seconds.
        retry_backoff_s: wait before the single retry of a timeout/connection error/5xx.

    Raises:
        SecConfigError: if no usable contact email is available.
    """

    # Shared across instances: Streamlit may create a new client on every rerun.
    _rate_lock = threading.Lock()
    _last_request_at: Optional[float] = None

    def __init__(self, contact_email: Optional[str] = None, cache_dir: str = "data/cache",
                 cache_ttl_hours: int = 24, min_interval_s: float = 0.15, *,
                 session: Optional[Any] = None,
                 clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep,
                 timeout_s: float = 15.0,
                 retry_backoff_s: float = 1.0) -> None:
        email = contact_email if contact_email is not None else config.SEC_CONTACT_EMAIL
        email = (email or "").strip()
        if not email or "@" not in email:
            raise SecConfigError()
        self._headers = {
            "User-Agent": f"{config.APP_NAME} {email}",
            "Accept-Encoding": "gzip, deflate",
        }
        self._cache_dir = Path(cache_dir)
        self._cache_ttl_s = cache_ttl_hours * 3600.0
        self._min_interval_s = min_interval_s
        self._session = session if session is not None else requests.Session()
        self._clock = clock
        self._now = now
        self._sleep = sleep
        self._timeout_s = timeout_s
        self._retry_backoff_s = retry_backoff_s

    @classmethod
    def _reset_rate_limit_state(cls) -> None:
        """Forget the shared last-request time (used by tests)."""
        with cls._rate_lock:
            cls._last_request_at = None

    # ------------------------------------------------------------------ public API

    def get_company_tickers(self) -> dict:
        """company_tickers.json: ticker/name/CIK list."""
        return self._get_json(TICKERS_URL, "company_tickers", _is_valid_tickers)

    def get_submissions(self, cik: str) -> dict:
        """Submissions JSON (name, SIC code, filings) for a CIK.

        Raises ValueError for an invalid CIK (see pad_cik).
        """
        padded = pad_cik(cik)
        return self._get_json(SUBMISSIONS_URL.format(cik=padded), f"submissions_CIK{padded}",
                              _is_valid_submissions)

    def get_company_facts(self, cik: str) -> dict:
        """XBRL companyfacts JSON for a CIK.

        Raises ValueError for an invalid CIK (see pad_cik).
        """
        padded = pad_cik(cik)
        return self._get_json(COMPANY_FACTS_URL.format(cik=padded), f"companyfacts_CIK{padded}",
                              _is_valid_company_facts,
                              not_found_message=FACTS_NOT_FOUND_MESSAGE)

    # ------------------------------------------------------------------ internals

    def _get_json(self, url: str, cache_key: str, validator: Callable[[Any], bool],
                  not_found_message: Optional[str] = None) -> dict:
        """Return validated JSON from cache or the network; cache only valid successes."""
        cached = self._read_cache(cache_key, validator)
        if cached is not None:
            logger.debug("SEC cache hit: %s", cache_key)
            return cached
        try:
            response = self._request_with_retry(url)
        except SecNotFoundError:
            raise SecNotFoundError(not_found_message) from None
        data = self._parse_json(response)
        if not validator(data):
            logger.warning("Unexpected structure from SEC endpoint %s", url)
            raise SecMalformedResponseError()
        self._write_cache(cache_key, url, data)
        return data

    def _wait_for_rate_limit(self) -> None:
        """Sleep so that requests from ALL instances are >= min_interval_s apart."""
        cls = type(self)
        with cls._rate_lock:
            last = cls._last_request_at
            if last is not None:
                wait = self._min_interval_s - (self._clock() - last)
                if wait > 0:
                    self._sleep(wait)
            cls._last_request_at = self._clock()

    def _send(self, url: str) -> Any:
        """One HTTP attempt. Returns the response on 2xx, otherwise raises a mapped error."""
        self._wait_for_rate_limit()
        try:
            response = self._session.get(url, headers=dict(self._headers),
                                         timeout=self._timeout_s)
        except requests.exceptions.Timeout:
            logger.info("SEC request timed out: %s", url)
            raise SecUnavailableError() from None
        except requests.exceptions.RequestException:
            logger.info("SEC connection error: %s", url)
            raise SecUnavailableError() from None

        status = response.status_code
        logger.debug("SEC GET %s -> %s", url, status)
        if 200 <= status < 300:
            return response
        if status == 404:
            raise SecNotFoundError()
        if status == 429:
            raise SecRateLimitError()
        if status == 403:
            body = (getattr(response, "text", "") or "").lower()
            if any(hint in body for hint in _RATE_LIMIT_HINTS):
                raise SecRateLimitError()
            raise SecClientError("The SEC refused this request (HTTP 403). Please try again "
                                 "later, or provide the figures via PDF upload or manual entry.")
        if status >= 500:
            raise SecUnavailableError()
        raise SecClientError(f"The SEC returned an unexpected response (HTTP {status}). Please "
                             "try again later, or provide the figures via PDF upload or "
                             "manual entry.")

    def _request_with_retry(self, url: str) -> Any:
        """Send once; on SecUnavailableError wait retry_backoff_s and retry exactly once."""
        try:
            return self._send(url)
        except SecUnavailableError:
            logger.info("Retrying SEC request once after %.1fs: %s", self._retry_backoff_s, url)
            self._sleep(self._retry_backoff_s)
            return self._send(url)

    @staticmethod
    def _parse_json(response: Any) -> Any:
        """Parse the response body as JSON or raise SecMalformedResponseError."""
        try:
            return response.json()
        except ValueError:  # includes json / requests JSONDecodeError
            raise SecMalformedResponseError() from None

    # ------------------------------------------------------------------ cache

    def _cache_path(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str, validator: Callable[[Any], bool]) -> Optional[dict]:
        """Return cached data if fresh and valid; anything odd counts as a miss."""
        if self._cache_ttl_s <= 0:
            return None
        path = self._cache_path(cache_key)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                envelope = json.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.debug("Ignoring unreadable SEC cache file: %s", path.name)
            return None
        if not isinstance(envelope, dict):
            return None
        fetched_at = envelope.get("fetched_at")
        data = envelope.get("data")
        if not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
            return None
        age = self._now() - fetched_at
        if age < 0 or age >= self._cache_ttl_s:
            return None
        if not validator(data):
            logger.debug("Ignoring SEC cache file with unexpected structure: %s", path.name)
            return None
        return data

    def _write_cache(self, cache_key: str, url: str, data: Any) -> None:
        """Atomically write a cache entry; failure to cache is logged, never fatal."""
        envelope = {"fetched_at": self._now(), "url": url, "data": data}
        tmp_name: Optional[str] = None
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=self._cache_dir, prefix=f".{cache_key}.",
                                            suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh)
            os.replace(tmp_name, self._cache_path(cache_key))
            tmp_name = None
        except OSError:
            logger.warning("Could not write SEC cache file for %s", cache_key)
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
