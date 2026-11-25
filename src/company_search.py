"""Owned by Person 2: company name/ticker search."""
from __future__ import annotations

from typing import Optional

from src.models import CompanyMatch
from src.sec_client import SecClient


def search_companies(query: str, client: Optional[SecClient] = None,
                     limit: int = 10) -> list[CompanyMatch]:
    """Return ranked matches for a name or ticker."""
    raise NotImplementedError("Owned by Person 2, not built yet")
