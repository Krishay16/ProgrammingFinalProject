"""Owned by Person 2: end-to-end public data retrieval."""
from __future__ import annotations

from typing import Optional

from src.models import CompanyMatch, PublicDataResult
from src.sec_client import SecClient


def fetch_public_financials(match: CompanyMatch,
                            client: Optional[SecClient] = None) -> PublicDataResult:
    """Fetch and normalise public financials for a confirmed company."""
    raise NotImplementedError("Owned by Person 2, not built yet")
