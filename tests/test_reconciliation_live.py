"""LIVE reconciliation test (Person 2). Calls SEC EDGAR; skipped by default.

Run with:  pytest -m live tests/test_reconciliation_live.py

Fetches FRESH app values (same code as the app) into tmp_path, so docs/ is not touched, and
compares them with the hand-typed figures in docs/reconciliation_expected.csv.
Skips (does not fail) when no filing value has been typed yet.
Strict: fails on MISMATCH, INPUT ERROR, APP VALUE MISSING or NO APP ROW for any typed row,
even if that row has an explanation.
"""
from __future__ import annotations

import pytest

from scripts import reconcile as rc
from src.sec_client import SecClient, SecConfigError

pytestmark = pytest.mark.live


def test_app_values_match_hand_typed_filing_values(tmp_path):
    if not rc.EXPECTED_CSV.exists():
        pytest.skip(f"{rc.EXPECTED_CSV} does not exist yet (run scripts/reconcile.py first).")
    expected = rc.read_csv(rc.EXPECTED_CSV)
    filled = [r for r in expected if r.get("filing_value_as_printed", "").strip()]
    if not filled:
        pytest.skip("No filing values typed in docs/reconciliation_expected.csv yet.")

    try:
        client = SecClient(cache_dir=str(rc.CACHE_DIR))
    except SecConfigError:
        pytest.skip("SEC_CONTACT_EMAIL is not set in .env; cannot call SEC EDGAR.")

    tickers = sorted({r["ticker"].strip().upper() for r in filled})
    app_csv = tmp_path / "app_values.csv"
    rc.run_fetch(tickers, client, app_csv, tmp_path / "unused_expected.csv", out=lambda s: None)
    comps = rc.compare(filled, rc.read_csv(app_csv))

    failures = [c for c in comps if c.status is not rc.Status.MATCH]
    detail = "\n".join(
        f"{'/'.join(c.key)}: {c.status.value} app={c.app_value} filing={c.filing_value} "
        f"diff={c.difference} {c.error}".rstrip() for c in failures)
    assert not failures, f"{len(failures)} typed figure(s) do not match:\n{detail}"
