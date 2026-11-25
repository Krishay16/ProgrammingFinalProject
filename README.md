# SolvIQ

**Smarter Corporate Credit Decisions, Powered by AI.**

SolvIQ is a Streamlit web app that helps corporate credit analysts do a **first-pass credit risk screen** of a non-financial company. The analyst searches for a company, the app retrieves up to three years of annual financial statements from SEC EDGAR (or the analyst uploads PDF statements or types the figures in), and a deterministic engine computes financial ratios, an illustrative screening score and rule-based risk alerts. A dashboard presents the results with charts, a written commentary and a downloadable report.

It is built for credit analysts, commercial lending teams and credit risk departments who today collect figures by hand from filings into spreadsheets. Every figure keeps its source, and the analyst confirms any PDF or manual values before they are used.

> **This is a screening aid, not a credit rating, not a probability of default and not a lending decision.** The score is illustrative and is no substitute for professional credit judgment.

## Install

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and set `SEC_CONTACT_EMAIL` to your own email. The SEC asks automated clients to identify themselves. All other settings are optional and the app runs without them.

## Run

```bash
streamlit run app.py
```

Use **Load SYNTHETIC demo company** in the sidebar to try the app without any real data.

## Test

```bash
pytest              # offline tests only (default)
pytest -m live      # tests that call the real SEC API (needs network and SEC_CONTACT_EMAIL)
```

## Repository layout

| Path | Owner | Purpose |
|---|---|---|
| `app.py`, `src/config.py`, `src/models.py`, `src/state.py`, `src/data_validation.py`, `src/ui/theme.py`, `tests/fixtures/sample_data.py` | Person 1 | App shell, shared data model, validation, synthetic fixtures |
| `src/sec_client.py`, `src/company_search.py`, `src/financial_normalizer.py`, `src/public_data.py`, `src/ui/search_page.py`, `scripts/reconcile.py` | Person 2 | SEC EDGAR search and data |
| `src/pdf_extractor.py`, `src/manual_input.py`, `src/ui/upload_page.py`, `src/ui/manual_page.py`, `src/ui/confirm_table.py` | Person 3 | PDF and manual input |
| `src/financial_calculations.py`, `src/credit_scoring.py`, `src/risk_alerts.py`, `src/engine.py`, `src/scenario.py`, `src/ui/scenario_page.py` | Person 4 | Ratios, score, alerts, stress test |
| `src/ui/dashboard_page.py`, `src/charts.py`, `src/ai_analyst.py`, `src/report_generator.py`, `src/ui/methodology_page.py` | Person 5 | Dashboard, commentary, report |
| `docs/` | shared | Architecture, methodology, data sources, reconciliation, business plan |

## Data sources

- **SEC EDGAR** (free official API): annual 10-K data for US-listed filers.
- **User-uploaded PDF statements**: processed locally in memory, never stored.
- **Manual entry**: figures typed in by the analyst.

No paid data and no scraping. Missing values are always `None`, never `0`.

## Known limitations

*To be completed after integration testing (Prompt 1.3).* Known so far:

- SEC EDGAR covers US filers only; non-US companies need PDF or manual input.
- Banks, insurers and other financial institutions are not supported by the scoring model.
- Scanned (image-only) PDFs are not read; there is no OCR in this version.
- Score thresholds are illustrative design assumptions, not validated banking standards.
- Pages for Persons 2 to 5 are placeholders until their pull requests are merged.

## Team workflow

One prompt = one branch = one pull request. Branches are prefixed by person (`p1/`, `p2/` ...). Never push directly to `main`. Each member commits from their own machine under their own git identity, opens a pull request and asks a teammate to review it by pulling the branch, running `pytest` and trying the page. Do not commit `.env`, secrets or real company PDFs.
