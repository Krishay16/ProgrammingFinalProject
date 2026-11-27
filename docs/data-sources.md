# Data sources

Owner: Person 2 (Public data). Code: `src/sec_client.py`.

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

## Testing

`tests/test_sec_client.py` runs fully offline with a fake HTTP session and a fake clock. One
optional live test (`@pytest.mark.live`) calls the real ticker endpoint. It is skipped by
default; run it with `pytest -m live`, which needs `SEC_CONTACT_EMAIL` set.
