"""App-wide constants, exact UI texts and optional .env settings. Owned by Person 1.

Import these texts everywhere; never retype them.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# The app name lives here only (single source of truth); every other module imports it.
APP_NAME = "SolvIQ"
TAGLINE = "Smarter Corporate Credit Decisions, Powered by AI."
HOME_HEADING = "Analyze Any Company's Financial Health"
HOME_SUBTITLE = ("Enter a company name to discover publicly available financial statements "
                 "and generate an AI-assisted credit risk assessment.")
NO_DATA_MESSAGE = ("We couldn't find publicly available financial statements for this company "
                   "in our supported data sources.\n\n"
                   f"{APP_NAME} can still perform a financial assessment if you provide the "
                   "company's financial information.\n\n"
                   "Please choose one of the following options to continue.")
NO_DATA_FOOTNOTE = ("Public data availability varies by country, company type, reporting "
                    "framework and filing requirements. This message does not necessarily mean "
                    "the company has never published financial statements.")
SCORE_DISCLAIMER = (f"{APP_NAME} provides an illustrative financial risk screening score, not an "
                    "agency credit rating, a validated default probability, or a substitute for "
                    "professional credit judgment.")
INSUFFICIENT_SCORE_LABEL = "Insufficient Data — Full Credit Score Unavailable"
SCENARIO_LABEL = "Illustrative Stress Scenario — Not Reported Financials"
FINANCIAL_INSTITUTION_MESSAGE = (
    "This company appears to be a bank, insurer or other financial "
    "institution. Conventional industrial-company ratios may be inappropriate, so it is not "
    "supported by the current scoring model.")
RISK_BANDS = [(80, "Lower Indicative Financial Risk"), (60, "Moderate Indicative Financial Risk"),
              (40, "Elevated Indicative Financial Risk"), (0, "High Indicative Financial Risk")]
CURRENCIES = ["USD", "EUR", "GBP", "MAD"]
PAGES = ["Search", "Upload PDF", "Manual Entry", "Dashboard", "Stress Scenario", "Methodology"]


def _env(name: str) -> str | None:
    """Return a stripped env var, or None when unset/blank."""
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


# Optional settings (the app must work with none set).
SEC_CONTACT_EMAIL: str | None = _env("SEC_CONTACT_EMAIL")
LLM_PROVIDER: str = (_env("LLM_PROVIDER") or "none").lower()
LLM_API_KEY: str | None = _env("LLM_API_KEY")
LLM_MODEL: str | None = _env("LLM_MODEL")
