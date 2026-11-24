"""Owned by Person 3: PDF text/table extraction into candidate financial values."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PdfExtractionResult(BaseModel):
    """TODO(Person 3): define the real fields (items, fiscal_years, currency, units,
    warnings, scanned_files, failed_files) as described in the prompt."""


def parse_number(text: str) -> Optional[float]:
    """Parse '1,234', '(1,234)', '1.234,56' ... into a float, or None."""
    raise NotImplementedError("Owned by Person 3, not built yet")


def extract_financials(files: list[tuple[str, bytes]]) -> PdfExtractionResult:
    """Extract candidate figures from (filename, bytes) PDF pairs, in memory only."""
    raise NotImplementedError("Owned by Person 3, not built yet")
