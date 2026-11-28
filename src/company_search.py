"""Owned by Person 2: company name/ticker search over the SEC ticker list.

``search_companies`` matches a free-text query against SEC ``company_tickers.json``
(one row per TICKER, so one company can appear several times, e.g. share classes).

Matching rules (also in docs/data-sources.md, "Company search"):

* Names are normalized the same way on both sides: case-insensitive, accents removed,
  apostrophes deleted ("McDonald's" -> "mcdonalds"), SEC state tags like "/DE/" removed, other
  punctuation turned into spaces ("Coca-Cola" -> "coca cola"), a leading "the" and trailing
  legal suffixes (Inc, Incorporated, Corp, Corporation, Co, Company, Ltd, Limited, PLC,
  Holdings, Holding, LLC) removed.
* Tickers are compared case-insensitively with "." and "-" treated as equal (BRK.B = BRK-B).
* Tiers and fixed scores (CompanyMatch.match_score is for ranking only):
    1. exact ticker ............................................... 1.0
    2. exact normalized name (also with spaces removed) ........... 0.95
    3. name starts with the query ................................. 0.85
    4. query appears as whole word(s) inside the name ............. 0.7
    5. fuzzy (difflib ratio >= FUZZY_THRESHOLD), only if tiers 1-4
       found fewer than ``limit`` companies ....................... ratio * 0.6
  Queries shorter than 2 characters (after normalization) only use tiers 1-2.
  Within a tier: shorter names first, then alphabetical, then SEC file order (so for share
  classes the first-listed ticker, usually the primary one, is shown).
* Results are de-duplicated by CIK, keeping the best-ranked row; CIKs are 10-digit padded.
* An empty query, or one that is empty after removing punctuation/suffixes ("Inc", "The"),
  returns []. Odd query text never raises.
* SEC errors (SecClientError subclasses: unavailable, rate limited, config ...) are NOT
  swallowed: they propagate so the UI can say "SEC unavailable" instead of "no company found".
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from src.models import CompanyMatch
from src.sec_client import SecClient, pad_cik

SCORE_TICKER = 1.0
SCORE_EXACT_NAME = 0.95
SCORE_STARTS_WITH = 0.85
SCORE_CONTAINS = 0.7
FUZZY_WEIGHT = 0.6
FUZZY_THRESHOLD = 0.8
MIN_PARTIAL_QUERY_LEN = 2

LEGAL_SUFFIXES = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
    "holdings", "holding", "llc",
})
_STATE_TAG = re.compile(r"/[a-z]{2,3}/")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _Row:
    """One ticker row of the SEC list, with precomputed match keys."""
    cik: str
    ticker: Optional[str]
    title: str
    name_key: str     # normalized, words separated by single spaces
    compact_key: str  # normalized, no spaces
    ticker_key: str   # normalized ticker ("" if none)
    order: int        # position in the SEC file (earlier = usually the primary listing)


def _normalize_name(text: str, keep_if_empty: bool = False) -> str:
    """Normalize a company name or query for comparison (see module docstring).

    If removing "the"/suffixes would leave nothing and ``keep_if_empty`` is True (used for
    SEC titles), the unstripped words are kept so the row stays searchable.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    s = ascii_text.lower().replace("'", "")
    s = _STATE_TAG.sub(" ", s)
    words = _NON_ALNUM.sub(" ", s).split()
    stripped = list(words)
    if stripped and stripped[0] == "the":
        stripped = stripped[1:]
    while stripped and stripped[-1] in LEGAL_SUFFIXES:
        stripped.pop()
    if not stripped and keep_if_empty:
        stripped = words
    return " ".join(stripped)


def _normalize_ticker(text: str) -> str:
    """Upper-case ticker with "." and "-" treated as equal (BRK.B -> BRK-B)."""
    return text.strip().upper().replace(".", "-")


def _build_rows(tickers: dict) -> list[_Row]:
    """Turn company_tickers.json into searchable rows; unusable rows are skipped."""
    rows: list[_Row] = []
    for order, entry in enumerate(tickers.values()):
        if not isinstance(entry, dict):
            continue
        try:
            cik = pad_cik(entry.get("cik_str"))
        except ValueError:
            continue
        title = str(entry.get("title") or "").strip()
        ticker = str(entry.get("ticker") or "").strip() or None
        if not title and not ticker:
            continue
        name_key = _normalize_name(title, keep_if_empty=True)
        rows.append(_Row(cik=cik, ticker=ticker, title=title or (ticker or ""),
                         name_key=name_key, compact_key=name_key.replace(" ", ""),
                         ticker_key=_normalize_ticker(ticker) if ticker else "",
                         order=order))
    return rows


def _tier_score(row: _Row, q_key: str, q_compact: str, q_ticker: str) -> Optional[float]:
    """Score of the best deterministic tier (1-4) a row matches, or None."""
    if q_ticker and row.ticker_key == q_ticker:
        return SCORE_TICKER
    if row.name_key and (row.name_key == q_key or row.compact_key == q_compact):
        return SCORE_EXACT_NAME
    if len(q_compact) < MIN_PARTIAL_QUERY_LEN:
        return None
    if row.name_key.startswith(q_key) or row.compact_key.startswith(q_compact):
        return SCORE_STARTS_WITH
    if f" {q_key} " in f" {row.name_key} ":
        return SCORE_CONTAINS
    return None


def _fuzzy_score(row: _Row, q_key: str) -> Optional[float]:
    """difflib similarity * FUZZY_WEIGHT if above FUZZY_THRESHOLD, else None."""
    if not row.name_key:
        return None
    matcher = difflib.SequenceMatcher(None, q_key, row.name_key)
    if matcher.real_quick_ratio() < FUZZY_THRESHOLD or matcher.quick_ratio() < FUZZY_THRESHOLD:
        return None
    ratio = matcher.ratio()
    return ratio * FUZZY_WEIGHT if ratio >= FUZZY_THRESHOLD else None


def _rank_and_dedupe(scored: list[tuple[float, _Row]], limit: int) -> list[CompanyMatch]:
    """Sort by score (then shorter name, alphabetical, SEC file order); one row per CIK."""
    scored.sort(key=lambda sr: (-sr[0], len(sr[1].name_key), sr[1].title, sr[1].order))
    seen: set[str] = set()
    matches: list[CompanyMatch] = []
    for score, row in scored:
        if row.cik in seen:
            continue
        seen.add(row.cik)
        matches.append(CompanyMatch(name=row.title, ticker=row.ticker, cik=row.cik,
                                    match_score=round(score, 4)))
        if len(matches) >= limit:
            break
    return matches


def search_companies(query: str, client: Optional[SecClient] = None,
                     limit: int = 10) -> list[CompanyMatch]:
    """Return up to ``limit`` companies matching a name or ticker, best first.

    Args:
        query: company name, partial name or ticker typed by the analyst.
        client: SecClient to use (a default one is created if None).
        limit: maximum number of companies returned.

    Returns:
        Ranked, CIK-de-duplicated matches; [] for an empty/meaningless query.

    Raises:
        SecClientError (or a subclass): if the SEC ticker list cannot be obtained. This is
            deliberate, so the UI can distinguish "SEC unavailable" from "no match".
    """
    if not isinstance(query, str) or limit <= 0:
        return []
    q_key = _normalize_name(query)
    if not q_key:
        # Empty, or only punctuation / "the" / legal suffixes: nothing meaningful to search.
        return []
    q_ticker = _normalize_ticker(query)
    q_compact = q_key.replace(" ", "")

    sec = client if client is not None else SecClient()
    rows = _build_rows(sec.get_company_tickers())

    scored: list[tuple[float, _Row]] = []
    unmatched: list[_Row] = []
    for row in rows:
        score = _tier_score(row, q_key, q_compact, q_ticker)
        if score is None:
            unmatched.append(row)
        else:
            scored.append((score, row))

    if len({row.cik for _s, row in scored}) < limit and len(q_compact) >= MIN_PARTIAL_QUERY_LEN:
        matched_ciks = {row.cik for _s, row in scored}
        for row in unmatched:
            if row.cik in matched_ciks:
                continue
            fuzzy = _fuzzy_score(row, q_key)
            if fuzzy is not None:
                scored.append((fuzzy, row))

    return _rank_and_dedupe(scored, limit)
