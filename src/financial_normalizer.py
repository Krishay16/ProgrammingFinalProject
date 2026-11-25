"""Owned by Person 2: SEC companyfacts JSON -> CompanyFinancials."""
from __future__ import annotations

from src.models import CompanyFinancials, CompanyInfo


def normalize_company_facts(facts: dict, company: CompanyInfo,
                            max_periods: int = 3) -> CompanyFinancials:
    """Convert SEC companyfacts JSON into the shared data model."""
    raise NotImplementedError("Owned by Person 2, not built yet")
