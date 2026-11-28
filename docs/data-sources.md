# Data sources

Owner: Person 2 (Public data). Code: `src/sec_client.py` (HTTP client),
`src/company_search.py` (name/ticker search), `src/financial_normalizer.py` (SEC data ->
shared data model).

## Summary

SolvIQ uses **one** public data source: the official, free **SEC EDGAR APIs** of the U.S.
Securities and Exchange Commission. We use **no paid data, no scraped websites and no
third-party data vendors**, and no API key is needed. If the SEC has no usable data for a
company, the analyst can upload PDF statements or enter the figures by hand instead.

Official documentation:
<https://www.sec.gov/search-filings/edgar-application-programming-interfaces>

## Endpoints we call

| Endpoint | URL | What we use it for |
|---|---|---|
| Ticker list | `https://www.sec.gov/files/company_tickers.json` | Look up a company by name or ticker and get its CIK (the SEC's company ID). |
| Submissions | `https://data.sec.gov/submissions/CIK##########.json` | Company name, SIC industry code (for example, to spot banks and insurers), fiscal year end and the list of filings (10-K and so on). |
| Company facts | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | Structured (XBRL) financial statement figures, such as revenue, debt and cash flow, for up to 3 annual periods. |

`##########` is the CIK padded with zeros to 10 digits, e.g. Microsoft = `0000789019`
(see `pad_cik`).

## SEC access rules we follow

1. **We identify ourselves.** Every request sends a `User-Agent` header of the form
   `SolvIQ <contact email>`, as the SEC requires. The email comes from `SEC_CONTACT_EMAIL`
   in the local `.env` file. If it is missing or does not contain `@`, the client refuses to
   run and asks the user to set it. The email is never written to logs or error messages.
   We also send `Accept-Encoding: gzip, deflate`.
2. **We stay well under the rate limit.** The SEC allows at most 10 requests per second. We
   wait at least 0.15 s between any two requests (at most about 6.7 per second). This limit
   is shared by every client object in the app, so a Streamlit rerun cannot bypass it.
3. **We cache.** Successful responses are saved in `data/cache/` (git-ignored) and reused for
   24 hours, so repeated searches do not hit the SEC again. Error responses are never cached.
   A damaged cache file is simply ignored and fetched again.
4. **We retry politely.** Each request has a 15 s timeout. After a timeout, a connection
   error or a server error (5xx), we wait briefly and retry **once**. We never retry 4xx
   errors.

## What errors mean for the user

| Situation | Error | Meaning shown to the user |
|---|---|---|
| `SEC_CONTACT_EMAIL` not set or invalid | `SecConfigError` | Set the email in `.env`. |
| HTTP 404 | `SecNotFoundError` | Not found at the SEC. For company facts, this usually means no structured financial data is available. It does **not** mean the company does not exist. |
| HTTP 429, or 403 mentioning rate limits or an undeclared automated tool | `SecRateLimitError` | The SEC is temporarily limiting us. Wait and retry. |
| Timeout, connection error, HTTP 5xx (after one retry) | `SecUnavailableError` | The SEC is unreachable. This is **not** proof that data is missing. |
| Not JSON, or not the expected structure | `SecMalformedResponseError` | Unexpected format. Try later or use PDF or manual entry. |
| Any other 4xx (including other 403s) | `SecClientError` | Generic refusal. Try later or use PDF or manual entry. |

## Setup

Copy `.env.example` to `.env` and set:

```
SEC_CONTACT_EMAIL=your.name@your-school-or-company.example
```

## Coverage limits (be honest with users)

EDGAR covers companies that file with the U.S. SEC. Many non-U.S. companies, private
companies, and companies that do not file XBRL financial data will **not** be found or
will have incomplete data. For those, the app offers PDF upload or manual entry.

## Company search (`src/company_search.py`)

`search_companies(query, client=None, limit=10)` searches the SEC ticker list. That file has
one row per **ticker**, so a company with several share classes appears several times.

* **Normalization (query and SEC names alike):** case-insensitive; accents removed;
  apostrophes deleted ("McDonald's" = "mcdonalds"); SEC state tags such as `/DE/` removed;
  other punctuation becomes a space ("Coca-Cola" = "coca cola"); a leading "The" and trailing
  legal suffixes (Inc, Incorporated, Corp, Corporation, Co, Company, Ltd, Limited, PLC,
  Holdings, Holding, LLC) are ignored.
* **Tickers:** case-insensitive, `.` and `-` are equal (BRK.B = BRK-B).
* **Ranking tiers** (fixed scores, used for ranking only):

  | Tier | Rule | Score |
  |---|---|---|
  | 1 | exact ticker | 1.0 |
  | 2 | exact normalized name (also ignoring spaces: "cocacola") | 0.95 |
  | 3 | name starts with the query | 0.85 |
  | 4 | query appears as whole word(s) in the name | 0.7 |
  | 5 | fuzzy (difflib similarity >= 0.8), only if tiers 1-4 found fewer than `limit` companies | similarity x 0.6 |

  Queries shorter than 2 characters only use tiers 1-2. Within a tier: shorter name first,
  then alphabetical, then SEC file order.
* **One result per company:** results are de-duplicated by CIK, keeping the best-ranked
  row (for share classes, the first-listed ticker). CIKs are 10-digit zero-padded.
* An empty query, or one that is empty after removing punctuation and suffixes ("Inc",
  "The"), returns no results without calling the SEC.
* **SEC errors are not hidden.** If the ticker list cannot be fetched (SEC unavailable, rate
  limited, missing contact email), the error is raised so the app can say "the SEC is
  unavailable" rather than wrongly saying "no company found".

## Selection policy (`src/financial_normalizer.py`)

`normalize_company_facts(facts, company, max_periods=3)` turns the SEC "company facts" JSON
into our shared `CompanyFinancials` model. These rules decide **which numbers we take**.

1. **US GAAP only.** We read the `us-gaap` section. If it is absent (for example IFRS / 20-F
   filers, which use `ifrs-full`) or empty, the result has no periods and a warning that
   suggests PDF upload or manual entry. Ordinary data problems never crash the app.
2. **Annual reports only.** A fact is used only if its form is `10-K` or `10-K/A` and its
   `fp` is `FY`. Quarterly reports (10-Q), proxy statements (DEF 14A), 8-Ks etc. are ignored.
3. **Periods are identified by their end date, not by `fy`.** In company facts, `fy` is the
   fiscal year of the *filing*, and each 10-K repeats earlier years. So a FY2024 number
   repeated in the FY2026 10-K is correctly filed under the period ending in 2024.
4. **Income-statement and cash-flow items must cover about one year:** 350 to 380 days from
   `start` to `end`. This accepts 52/53-week years (e.g. 364 or 371 days) and rejects
   quarters, even if a quarter is (wrongly or unusually) tagged `fp = FY`.
5. **Balance-sheet items** are point-in-time values taken **only at exactly** a fiscal year
   end date found in step 6.
6. **Fiscal year ends come from the data.** Candidate year ends are the end dates of one-year
   annual facts for net income, revenue, operating income and operating cash flow.
   Microsoft's year ends on 30 June; we never assume 31 December.
   `fiscal_year` = the calendar year in which the period ends.
7. **Core items:** a year end is used only if **net income** (one-year) **and total assets**
   (at that exact date) are both reported. Revenue may be missing. We take the latest
   `max_periods` (3) qualifying year ends, newest first.
8. **Two year ends in the same calendar year** (change of fiscal year end, or a 52/53-week year
   ending on 1-2 January): we keep the later one and add a warning.
9. **Duplicates** (same tag, same end date): the **most recently filed** value wins, so
   amendments (10-K/A) and restatements in later 10-Ks replace older figures. If two facts
   were filed on the same day, the higher accession number wins.
10. **Which tag per field.** Each field has an ordered list of candidates (below): reported
    tags first, then fallbacks. Among the **reported** tags, we first look for the
    highest-priority one that has a value in **all** selected years, and use it for every year,
    so the series is consistent. Only if no single reported tag covers all years does each
    year use its own first available candidate; then a warning lists the tag or method used
    per year, because definitions may differ.
    * **Fallbacks are gap fillers for single years.** They are used only for a year in which
      the field's reported tag(s) are missing, never for a year that reports the value, and
      never for all years just because they happen to cover them. The fallbacks are the
      **derivations** (short-term debt from components when `DebtCurrent` is missing,
      `LongTermDebt` minus `LongTermDebtCurrent` when `LongTermDebtNoncurrent` is missing,
      `LiabilitiesAndStockholdersEquity` minus equity when `Liabilities` is missing) and
      **restricted cash** (`CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` when
      `CashAndCashEquivalentsAtCarryingValue` is missing). Each year that uses restricted cash
      gets a warning: restricted cash may not be available to repay debt, so liquidity ratios
      may be overstated. If years mix a reported tag and a fallback, the usual tag-switch
      warning is also shown.
    * **Short-term debt from components:** if short-term debt is derived and not all three
      components (`LongTermDebtCurrent`, `CommercialPaper`, `ShortTermBorrowings`) are reported
      for a year, the value's note lists the missing ones, and **one** warning lists every
      affected year with its missing components: short-term debt and leverage ratios may be
      understated (e.g. Microsoft FY2026 reports only `LongTermDebtCurrent`).
11. **Currency:** we read currency units only (e.g. `USD`), never per-share units. A period is
    in USD when its net income is reported in USD, otherwise in the single other currency
    found. A number that exists only in a different currency is left blank with a warning:
    we never mix currencies in one period and never convert. If the selected years do not all
    use the same currency, one warning lists the currency per year (e.g. "FY2024: EUR;
    FY2025-FY2026: USD"): figures are still not converted, so comparisons across the change
    are not meaningful.
12. **Signs:** capital expenditure and interest expense are stored as positive amounts. If the
    SEC value was negative, the value's note says the sign was flipped. Everything else keeps
    its reported sign (losses negative; investing/financing cash flows keep their sign).
13. **Missing means blank.** A tag that is not reported gives an empty value (`None`), never 0,
    and a warning lists the missing fields for each year. **EBITDA is always left blank here**;
    the analysis engine derives it from EBIT + D&A.
14. **Traceability (provenance)** on every value: source "SEC EDGAR", the company facts URL with
    the 10-digit CIK, the filing (`10-K accn 0001193125-26-323660`), the filing date, the tag
    used and the raw reported number. Status is "source structured". Values we calculate
    ourselves are marked **derived** and their note lists the component tags and filings.
15. **Period filing date and form** are those of the net income fact chosen for that year,
    i.e. the **most recent filing that reported the period**. For an older year this is often
    a later 10-K that repeats it as a comparative (e.g. Microsoft FY2024 shows the 10-K filed
    in July 2026), because that is where the latest (possibly restated) figure comes from.
16. **Units:** XBRL values are already in full currency units, so `original_units = UNITS`.

### Candidate tags per field

| Field | Candidates, in priority order |
|---|---|
| Revenue | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet` |
| Cost of revenue | `CostOfRevenue`, `CostOfGoodsAndServicesSold` |
| Gross profit | `GrossProfit` |
| EBIT | `OperatingIncomeLoss` |
| Interest expense (stored positive) | `InterestExpense`, `InterestExpenseNonoperating`, `InterestExpenseDebt` |
| Net income | `NetIncomeLoss` |
| D&A | `DepreciationDepletionAndAmortization`, `DepreciationAndAmortization`, `DepreciationAmortizationAndAccretionNet` |
| Cash | `CashAndCashEquivalentsAtCarryingValue`; per-year gap filler `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`, only for a year where the first tag is missing (note and warning: includes restricted cash) |
| Current assets / Total assets / Current liabilities | `AssetsCurrent` / `Assets` / `LiabilitiesCurrent` |
| Total liabilities | `Liabilities`; for a year without it, **derived** `LiabilitiesAndStockholdersEquity` minus equity including non-controlling interest (or, if that is not reported, minus `StockholdersEquity`, with a note that the result may include non-controlling interest) |
| Total equity | `StockholdersEquity`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| Short-term debt | `DebtCurrent`; for a year without it, **derived** sum of whichever of `LongTermDebtCurrent`, `CommercialPaper`, `ShortTermBorrowings` are reported (blank if none; note and warning list the missing components). Components are never added to `DebtCurrent` (no double counting). Leases and accounts payable are never included. |
| Long-term debt | `LongTermDebtNoncurrent`; for a year without it, **derived** `LongTermDebt` minus `LongTermDebtCurrent`, only if both are reported |
| Operating / investing / financing cash flow | `NetCashProvidedByUsedInOperatingActivities` / `...InvestingActivities` / `...FinancingActivities` |
| Capex (stored positive) | `PaymentsToAcquirePropertyPlantAndEquipment` |
| EBITDA | not taken from the SEC (derived by the engine) |

### Known limitations

* **D&A is not available for some filers, e.g. Microsoft, so EBITDA-based ratios
  (EBITDA, net debt / EBITDA) are unavailable for them.** Microsoft reports none of our three
  D&A tags. It does report `Depreciation`, but we deliberately do not use it as D&A:
  depreciation alone would leave out amortization and understate EBITDA.
* Only the tags listed above are read. A company that uses another (e.g. company-specific)
  tag for a line item will show that field as missing; the analyst can complete it manually.
* Derived values (short-term debt from components, long-term debt, total liabilities) depend
  on what the company tags; the note on each value says exactly what was added or subtracted.
* Interest-expense tags are not perfectly uniform across companies (e.g. total interest
  expense vs non-operating interest expense); the tag used is shown on every value.

## Testing

`tests/test_sec_client.py` runs fully offline with a fake HTTP session and a fake clock. One
optional live test (`@pytest.mark.live`) calls the real ticker endpoint. It is skipped by
default; run it with `pytest -m live`, which needs `SEC_CONTACT_EMAIL` set.

`tests/test_company_search.py` and `tests/test_data_normalization.py` run offline on fixtures
in `tests/fixtures/sec/`:

| Fixture | Content |
|---|---|
| `company_tickers_sample.json` | **Real** rows from the SEC ticker list (Apple, Microsoft, Tesla, Amazon, Coca-Cola and similarly named Coca-Cola companies, Alphabet and Berkshire Hathaway share classes, Apple Hospitality REIT), copied unchanged. |
| `microsoft_companyfacts_trimmed_fixture.json` | **Real** Microsoft company facts, trimmed: only the tags we read, facts ending on/after 2023-06-30, and non-10-K rows only for a few core tags. Values unchanged. |
| `SYNTHETIC_*_trimmed_fixture.json` | **Invented** values for edge cases: duplicates and amendments, quarterly noise, tag switches, debt fallbacks and signs, fiscal-year collision and 53-week years, non-USD filer. |

The real fixtures are rebuilt with `scripts/build_sec_fixtures.py` (not run by pytest). It
reads `data/cache/` and makes at most one live call (the ticker list) if it is not cached.
