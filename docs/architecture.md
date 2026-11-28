# Architecture

Everything flows through one shared data model, `CompanyFinancials` (`src/models.py`). Whatever the source, data is converted into this model, validated, confirmed by the analyst where needed, and only then analysed.

## Data flow

```mermaid
flowchart LR
    A[Search page] --> B[SecClient]
    B --> C[financial_normalizer]
    C --> F[(CompanyFinancials)]
    P[Upload PDF page] --> Q[pdf_extractor]
    Q --> T[Confirmation table]
    M[Manual Entry page] --> T
    T --> F
    F --> V[data_validation]
    F --> E[engine.run_analysis]
    V --> E
    E --> R[(AnalysisResult)]
    R --> D[Dashboard + charts]
    R --> AI[ai_analyst commentary]
    R --> RP[report_generator]
    F --> S[scenario]
    S --> SP[Stress Scenario page]
```

Text version:

1. **SEC route:** Search -> `SecClient` -> `normalize_company_facts` -> `CompanyFinancials`.
2. **PDF / manual route:** `pdf_extractor` or manual form -> editable confirmation table -> `CompanyFinancials` (values marked `USER_CONFIRMED`).
3. **Analysis:** `CompanyFinancials` -> `run_analysis` (validation + ratios + score + alerts) -> `AnalysisResult`.
4. **Output:** `AnalysisResult` -> dashboard, charts, commentary and downloadable report. `CompanyFinancials` -> `run_scenario` -> stress scenario page.

Pages never call each other directly. They share data only through `src/state.py` (`set_financials`, `get_financials`, `go_to`, ...).

## Key design rules

- Missing value = `None`, never `0`.
- Money is stored in full currency units; currencies are never converted.
- Each figure carries `Provenance` (source, location, original text, tag, verification status).
- If data is insufficient the score is `None` with an explanation; weights are never redistributed.
- **Coverage and interest expense** (current behaviour of `src/credit_scoring.py`):
  - If interest expense is reported as 0 and net debt ≤ 0, coverage gets full points (no debt to service).
  - If interest expense is missing, coverage cannot be scored. It is never treated as 0 interest. Because one
    factor is missing, there is no total and no risk band, and the result is "Insufficient Data — Full Credit
    Score Unavailable".
- Tests run offline; live-network tests are marked `live` and skipped by default.

## Decision log

| Date | Decision | Why | Who changes what |
|---|---|---|---|
| 2026-11-28 | Keep the current coverage rule for the MVP. The zero-debt rule and the partial score move to "Next steps / future work". | Exams and the Monday deadline. The demo company (MSFT) reports interest expense, so the demo is not affected. | P1: this doc and `docs/acceptance-tests.md`. No code change. |

## Next steps / future work

Agreed with Person 4 but not built for the MVP:

- **Zero debt is not missing data.** If short-term and long-term debt are both reported and sum to 0 (interest
  missing or 0), coverage gets full points with the message "No reported debt, so no interest burden." This is
  checked before the zero-interest rule above.
- **Missing interest with debt stays not scorable.** If interest expense is missing and debt is above 0 or unknown,
  coverage cannot be scored (as now).
- **Partial score.** If exactly one factor cannot be scored, the total stays `None` and no risk band is given. The
  explanation starts "Partial score: X of Y available points". X is the sum of the points from the factors that
  could be scored, and Y is their combined maximum (100 minus the missing factor's weight, so 80 when coverage is
  missing). Weights are never redistributed. Two or more unscored factors still give "Insufficient Data — Full
  Credit Score Unavailable".
- Why it matters: some companies on SEC data (for example Apple) have no interest expense tag, so today they get no
  score at all.

## Module ownership

| Module | Owner |
|---|---|
| `app.py`, `src/models.py`, `src/config.py`, `src/state.py`, `src/data_validation.py`, `src/ui/theme.py`, `tests/fixtures/sample_data.py` | Person 1 |
| `src/sec_client.py`, `src/company_search.py`, `src/financial_normalizer.py`, `src/public_data.py`, `src/ui/search_page.py`, `scripts/reconcile.py` | Person 2 |
| `src/pdf_extractor.py`, `src/manual_input.py`, `src/ui/upload_page.py`, `src/ui/manual_page.py`, `src/ui/confirm_table.py` | Person 3 |
| `src/financial_calculations.py`, `src/credit_scoring.py`, `src/risk_alerts.py`, `src/engine.py`, `src/scenario.py`, `src/ui/scenario_page.py` | Person 4 |
| `src/charts.py`, `src/ai_analyst.py`, `src/report_generator.py`, `src/ui/dashboard_page.py`, `src/ui/methodology_page.py` | Person 5 |
