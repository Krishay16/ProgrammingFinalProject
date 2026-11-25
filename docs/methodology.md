# SolvIQ methodology: ratios, illustrative score, alerts and stress scenario

Owner: Person 4. Code: `src/financial_calculations.py`, `src/credit_scoring.py`,
`src/risk_alerts.py`, `src/engine.py`, `src/scenario.py`.

> SolvIQ provides an illustrative financial risk screening score, not an agency credit rating,
> a validated default probability, or a substitute for professional credit judgment.
> *(This is `config.SCORE_DISCLAIMER`.)*

**All weights, bands and alert thresholds below are illustrative design assumptions chosen
by the team for this MVP. They are NOT validated banking standards and have NOT been
calibrated against default data.** Sensible thresholds differ by industry (a utility
normally carries more leverage than a software company). The model covers non-financial
companies only.

---

## 1. General conventions

| Topic | Rule |
|---|---|
| Money | Stored in full currency units. The reporting currency is kept and never converted. |
| Missing value | `None`, never 0. A missing value is never filled with a guess. |
| Percentages | Stored as decimals (0.15 = 15%). `unit` is `x`, `%` or `currency`. |
| Rounding | Ratios are never rounded in calculations. Only the display rounds them. |
| Sign conventions | `capex` and `interest_expense` are positive amounts. Losses are negative. |
| Total debt | `short_term_debt + long_term_debt`, only when **both** are known. An analyst can type 0 for a component known to be zero. |
| EBITDA | The reported value is used if it exists. Otherwise it is derived as EBIT + D&A (the explanation says so). If neither is available, it is missing. |
| Money in explanations | Shown compactly: 1 billion or more → `1.2bn USD`; 1 million or more → `-500.0m USD`; otherwise `-12,345 USD`. The unit is chosen *after* rounding, so 999.96m shows as `1.0bn USD`. Stored values are never changed. |

### Ratio statuses

| Status | Meaning |
|---|---|
| `valid` | A value was calculated. |
| `unavailable` | At least one input is missing. |
| `undefined` | The inputs exist but the ratio is not meaningful (for example a zero or negative denominator, or an inconsistent sign). |

Every ratio carries an `explanation` that says why it is unavailable or undefined, plus
caveats such as "net cash position".

---

## 2. The 15 standard ratios

**Denominator rule.** Several ratios require a *strictly positive* denominator. A negative
denominator would flip the sign and mislead, so the ratio is UNDEFINED. This applies to:
current ratio and cash ratio (current liabilities), debt/equity (equity), debt/assets and
ROA (total assets), operating, net and FCF margins (revenue), net debt/EBITDA (EBITDA), and
revenue growth (prior revenue). A negative *numerator* is always allowed: for example, a
loss gives a negative margin.

| Key | Formula | Unit | Edge cases |
|---|---|---|---|
| `current_ratio` | Current assets / Current liabilities | x | CL ≤ 0 → undefined |
| `cash_ratio` | Cash and equivalents / Current liabilities | x | CL ≤ 0 → undefined |
| `working_capital` | Current assets − Current liabilities | currency | Negative is valid (explained) |
| `total_debt` | Short-term debt + Long-term debt | currency | Either component missing → unavailable |
| `debt_to_equity` | Total debt / Total equity | x | Equity 0 → undefined; equity < 0 → undefined ("negative equity: ratio not meaningful") |
| `debt_to_assets` | Total debt / Total assets | % | Total assets ≤ 0 → undefined |
| `net_debt` | Total debt − Cash | currency | Negative is valid = net cash position |
| `net_debt_to_ebitda` | (Total debt − Cash) / EBITDA | x | EBITDA ≤ 0 → undefined; negative result (net cash) is valid and explained |
| `operating_margin` | EBIT / Revenue | % | Revenue ≤ 0 → undefined; negative EBIT is valid |
| `net_profit_margin` | Net income / Revenue | % | Revenue ≤ 0 → undefined |
| `return_on_assets` | Net income / Total assets (end of period, not average) | % | Total assets ≤ 0 → undefined |
| `interest_coverage` | EBIT / Interest expense | x | Interest = 0 → undefined ("no interest expense reported"); interest < 0 → undefined (inconsistent sign) |
| `free_cash_flow` | Operating cash flow − Capex | currency | **Capex < 0 → undefined** (inconsistent sign: subtracting it would wrongly add cash); negative FCF is valid |
| `fcf_margin` | (OCF − Capex) / Revenue | % | Capex < 0 → undefined; Revenue ≤ 0 → undefined |
| `revenue_growth` | Revenue / Prior-year revenue − 1 | % | No prior year, gap year or missing revenue → unavailable. Not annual, different currency, prior revenue ≤ 0 or current revenue < 0 → undefined |

Revenue growth needs two consecutive annual fiscal years in the same currency.

---

## 3. Illustrative 0–100 screening score

The score uses the **latest** fiscal year only. Each factor earns a fraction (1.0 / 0.75 /
0.5 / 0.25 / 0) of its weight. The bands are checked from top to bottom and the first match
wins. **A value exactly on a boundary scores the higher band**, because the checks use `>=`
for "higher is better" and `<=` for "lower is better".

| Factor (weight) | Ratio | 100% | 75% | 50% | 25% | 0 |
|---|---|---|---|---|---|---|
| Liquidity (20) | Current ratio | ≥ 2.0x | ≥ 1.5x | ≥ 1.0x | ≥ 0.8x | below 0.8x |
| Leverage (25) | Debt / equity | ≤ 0.5x | ≤ 1.0x | ≤ 2.0x | ≤ 3.0x | above 3.0x |
| | Net debt / EBITDA | ≤ 1.0x | ≤ 2.0x | ≤ 3.0x | ≤ 4.0x | above 4.0x |
| Profitability (20) | Operating margin | ≥ 15% | ≥ 8% | ≥ 3% | ≥ 0% | below 0% |
| Coverage (20) | Interest coverage | ≥ 8x | ≥ 4x | ≥ 2x | ≥ 1x | below 1x |
| Cash flow (15) | FCF margin | ≥ 10% | ≥ 5% | ≥ 0% | — | below 0% |

**Leverage** is the average of the two ratio fractions × 25. Special rules:

- **Equity ≤ 0 → leverage scores 0 points.** This is a real balance-sheet weakness, not
  missing data. A high alert is also raised (section 4).
- **EBITDA ≤ 0 with net debt > 0** → the net debt/EBITDA half scores 0 and is averaged as
  normal.
- EBITDA ≤ 0 with a net cash position → net debt/EBITDA is not used, and only debt/equity
  counts.
- If one ratio is unavailable, the other is used alone. If neither can be used, leverage
  cannot be scored.
- Net cash (a negative net debt/EBITDA) is ≤ 1.0x, so it earns full marks.

**Coverage with zero interest expense:** full points (20) **only if net debt ≤ 0** (net
cash, so there is no debt to service). If net debt is positive, or cannot be calculated,
coverage cannot be scored.

### Risk bands (`config.RISK_BANDS`)

| Total | Category |
|---|---|
| ≥ 80 | Lower Indicative Financial Risk |
| ≥ 60 | Moderate Indicative Financial Risk |
| ≥ 40 | Elevated Indicative Financial Risk |
| ≥ 0 | High Indicative Financial Risk |

### Insufficient-data rule

If **any** of the five factors cannot be scored, the total is `None` and the UI shows
"Insufficient Data — Full Credit Score Unavailable". Weights are **never redistributed**,
and missing data is **never assumed to be good**. Partial factor scores are shown for
information only.

**Financial institutions** (`is_financial_institution = True`) get no score:
`config.FINANCIAL_INSTITUTION_MESSAGE` is shown instead.

### Worked example: SYNTHETIC `make_sample_financials()` FY2024 (millions USD)

| Factor | Calculation | Points |
|---|---|---|
| Liquidity | 4,800 / 2,600 = 1.85x → 75% band | 15 |
| Leverage | D/E 3,200 / 5,400 = 0.59x (75%); ND/EBITDA (3,200 − 1,500) / 1,800 = 0.94x (100%); average 87.5% × 25 | 21.875 |
| Profitability | 1,350 / 9,000 = 15.0% → exactly on the boundary, so the higher band applies | 20 |
| Coverage | 1,350 / 150 = 9.0x | 20 |
| Cash flow | (1,500 − 600) / 9,000 = 10.0% → exactly on the boundary | 15 |
| **Total** | | **91.875: Lower Indicative Financial Risk** |

SYNTHETIC `make_incomplete_financials()`: the factors that can be scored are liquidity 5
(0.82x), leverage 0 (equity is −500.0m USD) and profitability 10 (6.0%). Coverage cannot be
scored because interest expense is missing, and cash flow cannot be scored because OCF and
capex are missing. **The total is therefore insufficient.**

---

## 4. Risk alerts

Alerts are screening prompts for the latest fiscal year, plus one trend alert. They are
**not** evidence of default. Triggers are **strict**: a value exactly on the trigger does
**not** fire an alert. This is consistent with scoring, where a boundary value belongs to
the better band.

| Alert | Fires when | Low | Medium | High |
|---|---|---|---|---|
| Liquidity | Current ratio < 1.0x | 0.9 to < 1.0 | 0.75 to < 0.9 | < 0.75 |
| Leverage: D/E | Debt/equity > 2.0x | ≤ 3.0 | > 3.0 to ≤ 4.0 | > 4.0 |
| Leverage: ND/EBITDA | Net debt/EBITDA > 3.0x | ≤ 4.0 | > 4.0 to ≤ 5.0 | > 5.0 |
| Leverage: equity | Total equity ≤ 0 | — | — | always high |
| Coverage | Interest coverage < 2.0x | 1.5 to < 2.0 | 1.0 to < 1.5 | < 1.0 |
| Profitability | Operating margin < 0% | ≥ −5% | −15% to < −5% | < −15% |
| Cash flow | Free cash flow < 0 (severity from FCF margin) | ≥ −5% | −10% to < −5% | < −10% |
| Trend | Revenue growth < 0 in the latest **and** prior year (severity from the cumulative 2-year decline) | < 5% | 5% to < 15% | ≥ 15% |
| Data quality | Any of 12 key inputs missing | 1 missing | 2–3 missing | ≥ 4 missing |

Details:

- **Cash flow:** if FCF is negative but the FCF margin cannot be calculated, the severity
  is medium.
- **Data quality key inputs (12):** current assets, current liabilities, cash, short-term
  debt, long-term debt, total equity, revenue, EBIT, EBITDA, interest expense, operating
  cash flow and capex. EBITDA counts as missing only if it cannot be derived from EBIT + D&A.
- **Financial institutions:** all ratio alerts are suppressed, because industrial-company
  thresholds would mislead. Only the data-quality alert is kept.
- Each alert carries a `source_reference` that says where its inputs came from.

SYNTHETIC `make_incomplete_financials()` raises three alerts:
- liquidity, medium (current ratio 0.82x)
- negative equity, high
- data quality, high (4 missing: short-term debt, interest expense, OCF, capex)

The SYNTHETIC sample company raises no alerts.

---

## 5. Illustrative stress scenario

The page is always labelled **"Illustrative Stress Scenario — Not Reported Financials"**
(`config.SCENARIO_LABEL`).

**Inputs.** Four percentage changes, each between −90% and +200%.

**Method.** The latest period is **copied** and the original data is never modified. The
copy is changed as follows:

| Item | Change |
|---|---|
| Revenue | × (1 + revenue change) |
| EBIT | + \|EBIT\| × EBIT change. If EBIT is positive this is the same as × (1 + change). If EBIT is negative, a decline makes the loss **larger** and the assumptions say so. |
| Short-term and long-term debt | each × (1 + debt change) |
| Interest expense | × (1 + interest change) |
| Reported EBITDA | moved by the same absolute amount as EBIT. If EBITDA is not reported, the engine derives it from the stressed EBIT + D&A. |
| Everything else | unchanged |

**Recalculation and labelling:**
- Every changed value is marked `origin = derived` with the note "Illustrative stress
  scenario".
- A missing value stays missing.
- A 0% change leaves the value exactly as reported.
- Ratios and the score are recomputed with the same engine and bands as above. The prior
  year is unchanged, so revenue growth reflects the revenue shock.

### Limits (also listed on the page)

- Only the latest year is stressed.
- Cash, equity, total assets and liabilities, and current assets and liabilities are not
  adjusted.
- Net income, D&A, operating cash flow and capex are not adjusted, so the EBIT shock does
  **not** flow through to free cash flow.
- **Revenue and EBIT are shocked independently.** A revenue cut on its own (EBIT unchanged)
  mechanically **raises** operating margin and FCF margin. SYNTHETIC example: revenue −10%
  gives an operating margin of 1,350 / 8,100 = 16.7% (versus 15.0%) and an FCF margin of
  900 / 8,100 = 11.1% (versus 10.0%). It is therefore not a realistic downside on its own.
  **For a downside view, use a combined revenue + EBIT shock**, for example the
  "Revenue −10% and EBIT −25%" preset.
- A debt change does not change cash. Interest expense moves only with its own slider; it
  is not re-derived from the debt level.
- This is a mechanical sensitivity, not a forecast and not a probability of default.

### SYNTHETIC preset results (`make_sample_financials()` FY2024, base 91.875)

| Preset | Changed inputs (millions) | Factor points (liq / lev / prof / cov / cf) | Total |
|---|---|---|---|
| EBIT −20% | EBIT 1,080; EBITDA 1,530 | 15 / 18.75 (D/E 0.59x 75%, ND/EBITDA 1.11x 75%) / 15 (12.0%) / 15 (7.2x) / 15 | **78.75**: Moderate |
| Revenue −10% and EBIT −25% | Revenue 8,100; EBIT 1,012.5; EBITDA 1,462.5 | 15 / 18.75 (0.59x, 1.16x) / 15 (12.5%) / 15 (6.75x) / 15 (11.1%) | **78.75**: Moderate |
| Debt +30% | Debt 520 + 3,640 = 4,160 | 15 / 18.75 (D/E 0.77x, ND/EBITDA 2,660 / 1,800 = 1.48x) / 20 / 20 / 15 | **88.75**: Lower |

These values are checked by `tests/test_scenario.py`.
