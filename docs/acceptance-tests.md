# Acceptance tests

These are the checks the finished app must pass before submission. Each one describes what a credit analyst does and
what they must see. They cover the whole journey across all five parts, so they are run on `main` after the pull
requests are merged.

- **Automated** = covered by `pytest` (offline, no `.env` needed).
- **Manual** = run `streamlit run app.py` and follow the steps in a browser.
- **Status** = `Not run`, `Pass`, `Fail` (with a note), or `Blocked` (the part it needs is not merged yet).

Owner = the person whose module must make the test pass. Person 1 runs the full list after integration and records
the result.

## How to run

```bash
pytest                 # automated checks (offline)
pytest -m live         # SEC checks against the real API (needs network and SEC_CONTACT_EMAIL in .env)
streamlit run app.py   # manual checks, at http://localhost:8501
```

Use **Load SYNTHETIC demo company** in the sidebar for any test that needs data without the SEC or a PDF.

---

## 1. App shell and navigation (Person 1)

| ID | Steps | Expected result | Type | Status |
|---|---|---|---|---|
| A1.1 | Start the app with no `.env` file. | App opens on **Search**. No crash, no error about missing settings. | Manual + `test_app_smoke.py` | Not run |
| A1.2 | Click each of the six pages in the sidebar. | Each page opens. A page that fails shows "Something went wrong on this page…" and the rest of the app keeps working. | Manual + `test_app_smoke.py` | Not run |
| A1.3 | Click **Load SYNTHETIC demo company**. | Sidebar shows "Sample Manufacturing Co (SYNTHETIC)", FY2024, FY2023, FY2022 and "SYNTHETIC demo data, not a real company." | Manual + `test_app_smoke.py` | Not run |
| A1.4 | After A1.3, click **Reset**. | Sidebar shows "No company loaded". Dashboard no longer shows the demo company. | Manual + `test_app_smoke.py` | Not run |
| A1.5 | Look at the bottom of any page. | The score disclaimer is shown: "SolvIQ provides an illustrative financial risk screening score, not an agency credit rating…" | Manual + `test_app_smoke.py` | Not run |

## 2. Data validation (Person 1)

| ID | Steps | Expected result | Type | Status |
|---|---|---|---|---|
| A2.1 | Validate the SYNTHETIC demo company. | No errors and no warnings about the balance sheet or gross profit (assets = liabilities + equity in every year). | `test_data_validation.py` | Pass |
| A2.2 | Validate the SYNTHETIC incomplete company. | Warning "Negative equity…" for FY2024, and an info message listing the missing values (interest expense, short-term debt, the four cash-flow fields). | `test_data_validation.py` | Pass |
| A2.3 | A period where assets differ from liabilities + equity by more than 1%. | A warning asking the analyst to check the balance sheet. The value is not changed. | `test_data_validation.py` | Pass |
| A2.4 | Periods in two different currencies. | Warning that currencies are never converted. | `test_data_validation.py` | Pass |
| A2.5 | A missing value anywhere. | It stays empty (`None`). It is never shown or used as 0. | `test_models.py`, `test_data_validation.py` | Pass |

## 3. Company search and SEC data (Person 2)

| ID | Steps | Expected result | Type | Status |
|---|---|---|---|---|
| A3.1 | On **Search**, type a large US-listed company name. | A list of matching companies with ticker. The analyst picks one. | Manual + live test | Blocked |
| A3.2 | Pick the company from A3.1. | Up to three annual (10-K) years are loaded into the sidebar. Each figure carries its SEC source. | Manual + live test | Blocked |
| A3.3 | Search for a company the SEC does not cover (e.g. a non-US private company). | The "We couldn't find publicly available financial statements…" message and footnote appear, with buttons for **Upload PDF** and **Manual Entry**. | Manual | Blocked |
| A3.4 | Pick a bank or insurer. | The financial-institution message is shown and no score is produced. | Manual | Blocked |
| A3.5 | Run `pytest` with no network. | All SEC tests use saved responses in `tests/fixtures/sec/` and pass offline. | Automated | Blocked |

## 4. PDF upload and manual entry (Person 3)

| ID | Steps | Expected result | Type | Status |
|---|---|---|---|---|
| A4.1 | On **Upload PDF**, upload the SYNTHETIC sample statement PDF. | Extracted values appear in an editable confirmation table, each with the PDF location it came from. | Manual + `test_upload_page.py` | Not run |
| A4.2 | Change one value in the table and confirm. | The changed value is used. Confirmed values are marked as user-confirmed. | Manual + `test_manual_page.py` | Not run |
| A4.3 | Upload a scanned (image-only) PDF. | A clear message that the PDF could not be read, with a suggestion to use Manual Entry. No crash. | Manual | Not run |
| A4.4 | On **Manual Entry**, fill in one year and leave some fields empty. | Empty fields stay missing (not 0). Validation messages from section 2 appear before the analysis runs. | Manual + `test_manual_input.py` | Not run |
| A4.5 | Nothing from a PDF or manual entry is analysed before the analyst confirms it. | The Dashboard stays empty until **Confirm** is clicked. | Manual | Not run |

## 5. Ratios, score, alerts and stress scenario (Person 4)

Expected values below are hand-worked from the SYNTHETIC demo company, FY2024 (figures in millions, from
`tests/fixtures/sample_data.py`). They are not taken from the app's output. **Person 4: confirm each definition matches
the methodology. If a definition is different, the hand working must be redone, not copied from the app.**

| Ratio (FY2024) | Definition used here | Hand working | Expected |
|---|---|---|---|
| Current ratio | current assets ÷ current liabilities | 4,800 ÷ 2,600 | 1.85x |
| Debt to equity | (short-term + long-term debt) ÷ total equity | (400 + 2,800) ÷ 5,400 | 0.59x |
| Net debt to EBITDA | (total debt − cash) ÷ EBITDA | (3,200 − 1,500) ÷ 1,800 | 0.94x |
| Operating margin | EBIT ÷ revenue | 1,350 ÷ 9,000 | 15.0% |
| Interest coverage | EBIT ÷ interest expense | 1,350 ÷ 150 | 9.0x |
| Gross margin | gross profit ÷ revenue | 3,150 ÷ 9,000 | 35.0% |
| Net margin | net income ÷ revenue | 900 ÷ 9,000 | 10.0% |
| Free cash flow | operating cash flow − capex | 1,500 − 600 | 900 |

Note: operating margin is exactly 15.0%, which sits on a scoring threshold (≥ 15%). A rounding error in the code
would move it to the next band, so this is worth an automated test.

| ID | Steps | Expected result | Type | Status |
|---|---|---|---|---|
| A5.1 | Load the demo company and open **Dashboard**. | The ratios match the table above (to two decimals). | Automated + Manual | Blocked |
| A5.2 | Load the demo company. | A score from 0 to 100 with one of the four risk bands ("Lower / Moderate / Elevated / High Indicative Financial Risk"). | Automated + Manual | Blocked |
| A5.3 | Analyse the SYNTHETIC incomplete company (interest expense and cash flow missing). | No total score and no partial score (two factors cannot be scored). The label "Insufficient Data — Full Credit Score Unavailable" with an explanation. Weights are not redistributed. | Automated | Blocked |
| A5.6 | Demo company FY2024 with short-term and long-term debt set to 0 and interest expense removed (zero-debt case). | Coverage gets full points (20 of 20) with "No reported debt, so no interest burden." A full total score and risk band are shown, not "Insufficient Data". Hand working below. | Automated | Blocked |
| A5.7 | Demo company FY2024 with only interest expense removed (debt unchanged; the Apple case). | Coverage is "not scorable", never treated as 0 interest. "Partial score: 71.875 of 80 available points" (display may round). `total` is empty and no risk band is shown. Hand working below. | Automated | Blocked |
| A5.4 | Analyse the SYNTHETIC incomplete company (negative equity). | Leverage factor scores 0 and a risk alert about negative equity appears. | Automated | Blocked |
| A5.5 | On **Stress Scenario**, lower revenue by 20% and run. | Base and stressed results side by side, labelled "Illustrative Stress Scenario — Not Reported Financials". The original figures are unchanged. | Manual | Blocked |

Hand working for A5.6 and A5.7 (rule: `docs/architecture.md`, "Coverage with missing interest expense"). Bands and
weights are the ones written in `SCORING_CONFIG` on Person 4's `p4/score-alerts` branch. **Person 4: if those
thresholds change, redo this working by hand.**

| Factor (weight) | A5.7: interest expense missing | A5.6: zero debt, interest missing |
|---|---|---|
| Liquidity (20) | current ratio 1.85x → band ≥ 1.5x = 75% → 15 | same → 15 |
| Leverage (25) | D/E 0.59x → ≤ 1.0x = 75%; net debt/EBITDA 0.94x → ≤ 1.0x = 100%; average 87.5% → 21.875 | D/E 0 → 100%; net debt (0 − 1,500) ÷ 1,800 = −0.83x → 100% → 25 |
| Profitability (20) | operating margin 15.0% → ≥ 15% = 100% → 20 | same → 20 |
| Coverage (20) | not scorable (debt 3,200 > 0, interest missing) | no debt → full → 20 |
| Cash flow (15) | FCF margin 900 ÷ 9,000 = 10.0% → ≥ 10% = 100% → 15 | same → 15 |
| **Result** | **partial 71.875 of 80, no total, no band** | **total 95 of 100** |

## 6. Dashboard, commentary and report (Person 5)

| ID | Steps | Expected result | Type | Status |
|---|---|---|---|---|
| A6.1 | Load the demo company and open **Dashboard**. | Score, risk band, ratio table, charts across the three years and risk alerts are shown. | Manual | Blocked |
| A6.2 | Read the commentary with no LLM key set. | A written commentary still appears (the deterministic version). It does not contradict the score or the alerts. | Manual + Automated | Blocked |
| A6.3 | Download the report. | The file opens. It shows the company, years, source of the data, ratios, score, alerts and the disclaimer. Demo data is labelled SYNTHETIC. | Manual | Blocked |
| A6.4 | Open **Methodology**. | Explains each ratio, the score weights and thresholds, and says the thresholds are illustrative assumptions. | Manual | Blocked |
| A6.5 | Open **Dashboard** with no company loaded. | A friendly message pointing to Search, Upload PDF or Manual Entry. No error. | Manual | Blocked |

## 7. Whole journey (Person 1, after all merges)

| ID | Steps | Expected result | Type | Status |
|---|---|---|---|---|
| A7.1 | Search a US company → load SEC data → Dashboard → download report. | Works end to end with no error. Numbers on the dashboard and in the report match. | Manual | Blocked |
| A7.2 | Upload PDF → confirm → Dashboard → Stress Scenario → report. | Works end to end. Edited values are the ones analysed. | Manual | Blocked |
| A7.3 | Manual Entry → Dashboard → Reset → Search. | Reset clears everything. No figures from the previous company remain. | Manual | Blocked |
| A7.4 | `pytest` on `main` after all merges. | All tests pass, offline, without `.env`. | Automated | Not run |
| A7.5 | Search the repository for secrets and real PDFs. | No `.env`, no API keys and no real company PDFs are committed. | Manual | Not run |

## Results log

Add one line each time the list is run.

| Date | Commit on `main` | Run by | Result |
|---|---|---|---|
| | | | |
