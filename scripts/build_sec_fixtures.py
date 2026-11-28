"""Owned by Person 2: build the REAL trimmed SEC fixtures used by the offline tests.

NOT run by pytest. Run manually from the repository root:

    .venv/bin/python scripts/build_sec_fixtures.py

What it does:

1. tests/fixtures/sec/company_tickers_sample.json
   Filters the real SEC ticker list (data/cache/company_tickers.json if cached, otherwise ONE
   live call through SecClient, which needs SEC_CONTACT_EMAIL) down to a handful of rows.
   Rows are copied unchanged; nothing is typed in by hand.

2. tests/fixtures/sec/microsoft_companyfacts_trimmed_fixture.json
   Cuts the cached Microsoft companyfacts (data/cache/companyfacts_CIK0000789019.json; no
   network call) down to the us-gaap tags the normalizer reads, and to facts ending on or
   after FACTS_FROM. Values, dates, forms and accession numbers are copied unchanged.
   All 10-K/10-K/A rows are kept; quarterly (10-Q) and other-form rows are kept only for a few
   core tags (NOISE_TAGS), so tests prove they are ignored while the file stays small.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.financial_normalizer import ALL_TAGS  # noqa: E402
from src.sec_client import SecClient  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
OUT_DIR = ROOT / "tests" / "fixtures" / "sec"
MICROSOFT_CACHE = CACHE_DIR / "companyfacts_CIK0000789019.json"
TICKERS_CACHE = CACHE_DIR / "company_tickers.json"
MICROSOFT_OUT = OUT_DIR / "microsoft_companyfacts_trimmed_fixture.json"
TICKERS_OUT = OUT_DIR / "company_tickers_sample.json"

#: Facts ending before this date are dropped (keeps the fixture small).
FACTS_FROM = "2023-06-30"

#: All 10-K / 10-K/A rows are kept. Rows from other forms (10-Q, 8-K, DEF 14A ...) are kept
#: only for these tags, as realistic "noise" that the normalizer must ignore.
ANNUAL_FORMS = {"10-K", "10-K/A"}
NOISE_TAGS = {"NetIncomeLoss", "Assets", "RevenueFromContractWithCustomerExcludingAssessedTax"}

#: Rows are selected by these rules from the REAL list (tickers or title words).
SELECT_TICKERS = {"AAPL", "MSFT", "TSLA", "KO", "AMZN"}
SELECT_TITLE_WORDS = ("COCA", "BERKSHIRE HATHAWAY", "ALPHABET")
SELECT_TITLE_PREFIXES = ("APPLE",)


def _read_cache_data(path: Path) -> dict | None:
    """Return the "data" part of a SecClient cache envelope, or None if absent."""
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["data"]


def _write_json(path: Path, data: dict, indent: int | None = 1) -> None:
    """Write JSON; indent=None gives compact output (used for the larger fixture)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if indent is None:
            json.dump(data, fh, separators=(",", ":"))
        else:
            json.dump(data, fh, indent=indent)
        fh.write("\n")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def build_tickers_sample() -> None:
    """Filter the real ticker list down to the rows the search tests need."""
    tickers = _read_cache_data(TICKERS_CACHE)
    if tickers is None:
        tickers = SecClient().get_company_tickers()  # one live call (then cached)
    sample = {}
    for key, row in tickers.items():
        title = str(row.get("title", "")).upper()
        if (row.get("ticker") in SELECT_TICKERS
                or any(w in title for w in SELECT_TITLE_WORDS)
                or title.startswith(SELECT_TITLE_PREFIXES)):
            sample[key] = row
    _write_json(TICKERS_OUT, sample)


def build_microsoft_fixture() -> None:
    """Trim the cached Microsoft companyfacts to the tags and years the tests use."""
    data = _read_cache_data(MICROSOFT_CACHE)
    if data is None:
        raise SystemExit(f"Missing {MICROSOFT_CACHE}; fetch it first with "
                         "SecClient().get_company_facts('789019').")
    us_gaap = data["facts"]["us-gaap"]
    trimmed: dict[str, dict] = {}
    for tag in sorted(ALL_TAGS):
        if tag not in us_gaap:
            continue
        units = {unit: [f for f in rows if f.get("end", "") >= FACTS_FROM
                        and (f.get("form") in ANNUAL_FORMS or tag in NOISE_TAGS)]
                 for unit, rows in us_gaap[tag]["units"].items()}
        units = {u: rows for u, rows in units.items() if rows}
        if units:
            trimmed[tag] = {"units": units}
    fixture = {
        "_comment": ("REAL SEC data, trimmed by scripts/build_sec_fixtures.py from "
                     "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json: only "
                     f"the tags the normalizer reads, facts ending on/after {FACTS_FROM}, and "
                     "non-10-K rows only for NetIncomeLoss, Assets and RevenueFromContract"
                     "WithCustomerExcludingAssessedTax. Values are unchanged."),
        "cik": data["cik"],
        "entityName": data["entityName"],
        "facts": {"us-gaap": trimmed},
    }
    _write_json(MICROSOFT_OUT, fixture, indent=None)


if __name__ == "__main__":
    build_tickers_sample()
    build_microsoft_fixture()
