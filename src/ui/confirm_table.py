"""Owned by Person 3: shared editable confirmation table widget."""
from __future__ import annotations

from typing import Optional

import pandas as pd


def confirm_table(df: pd.DataFrame, key: str,
                  flags: Optional[dict[tuple[str, str], str]] = None) -> pd.DataFrame:
    """Show an editable table; return the edited DataFrame."""
    raise NotImplementedError("Owned by Person 3, not built yet")
