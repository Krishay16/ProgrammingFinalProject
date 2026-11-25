"""Owned by Person 2: SEC EDGAR HTTP client (headers, cache, rate limit, errors)."""
from __future__ import annotations

from typing import Optional


class SecClientError(Exception):
    """Base class for all SEC client errors."""


class SecConfigError(SecClientError):
    """Missing configuration, e.g. SEC_CONTACT_EMAIL not set."""


class SecNotFoundError(SecClientError):
    """The requested resource does not exist (HTTP 404)."""


class SecRateLimitError(SecClientError):
    """The SEC rate-limited or blocked the request."""


class SecUnavailableError(SecClientError):
    """Timeout, connection problem or 5xx from the SEC."""


class SecMalformedResponseError(SecClientError):
    """The SEC returned something that is not the expected JSON."""


class SecClient:
    """Polite SEC EDGAR client. Methods return parsed JSON dicts."""

    def __init__(self, contact_email: Optional[str] = None, cache_dir: str = "data/cache",
                 cache_ttl_hours: int = 24, min_interval_s: float = 0.15) -> None:
        raise NotImplementedError("Owned by Person 2, not built yet")

    def get_company_tickers(self) -> dict:
        """company_tickers.json: ticker/name/CIK list."""
        raise NotImplementedError("Owned by Person 2, not built yet")

    def get_submissions(self, cik: str) -> dict:
        """Submissions JSON (name, SIC code, filings) for a CIK."""
        raise NotImplementedError("Owned by Person 2, not built yet")

    def get_company_facts(self, cik: str) -> dict:
        """XBRL companyfacts JSON for a CIK."""
        raise NotImplementedError("Owned by Person 2, not built yet")
