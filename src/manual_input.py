"""Owned by Person 3: manual entry table <-> CompanyFinancials, JSON save/load."""
from __future__ import annotations

import pandas as pd

from src.models import CompanyFinancials, SourceType, Units


def empty_table(years: list[int]) -> pd.DataFrame:
    """Rows = ALL_FIELDS, columns = years (newest first), all missing."""
    raise NotImplementedError("Owned by Person 3, not built yet")


def table_to_financials(df: pd.DataFrame, company_name: str, currency: str, units: Units,
                        source_type: SourceType, source_ref: str) -> CompanyFinancials:
    """Convert a confirmed table into CompanyFinancials (full currency units)."""
    raise NotImplementedError("Owned by Person 3, not built yet")


def financials_to_json(f: CompanyFinancials) -> str:
    """Serialise for the 'save my working session' download."""
    raise NotImplementedError("Owned by Person 3, not built yet")


def financials_from_json(s: str) -> CompanyFinancials:
    """Load a previously saved working session."""
    raise NotImplementedError("Owned by Person 3, not built yet")
