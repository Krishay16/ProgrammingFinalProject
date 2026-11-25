"""Shared data contract for SolvIQ. Owned by Person 1.
Do not rename or remove fields without agreement from the whole team."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    SEC_EDGAR = "sec_edgar"
    PDF = "pdf"
    MANUAL = "manual"
    SYNTHETIC = "synthetic"  # demo/test data only, always labelled as such


class ValueOrigin(str, Enum):
    REPORTED = "reported"  # taken directly from a filing or document
    DERIVED = "derived"    # calculated by us from other values
    MANUAL = "manual"      # typed in by the analyst


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"                # extracted, not yet reviewed
    FLAGGED = "flagged"                      # ambiguous, must be reviewed before use
    USER_CONFIRMED = "user_confirmed"        # analyst confirmed or corrected it
    SOURCE_STRUCTURED = "source_structured"  # SEC XBRL fact with matching tag and period


class Units(int, Enum):
    UNITS = 1
    THOUSANDS = 1_000
    MILLIONS = 1_000_000
    BILLIONS = 1_000_000_000


class Provenance(BaseModel):
    source_type: SourceType
    source_ref: str                      # URL or file name
    location: Optional[str] = None       # e.g. "10-K accn 0000789019-24-000081" or "page 12"
    original_text: Optional[str] = None  # raw text as found, e.g. "(1,234)"
    tag: Optional[str] = None            # XBRL tag or PDF line label as found
    origin: ValueOrigin = ValueOrigin.REPORTED
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    filing_date: Optional[date] = None
    note: Optional[str] = None


class FinancialValue(BaseModel):
    value: Optional[float] = None        # None = MISSING. Never use 0 for missing.
    provenance: Optional[Provenance] = None

    @property
    def is_missing(self) -> bool:
        return self.value is None


FIELD_GROUPS: dict[str, list[str]] = {
    "balance_sheet": [
        "cash", "current_assets", "total_assets", "current_liabilities",
        "total_liabilities", "short_term_debt", "long_term_debt", "total_equity",
    ],
    "income_statement": [
        "revenue", "cost_of_revenue", "gross_profit", "ebit", "ebitda",
        "interest_expense", "net_income", "depreciation_amortization",
    ],
    "cash_flow": [
        "operating_cash_flow", "capex", "investing_cash_flow", "financing_cash_flow",
    ],
}
ALL_FIELDS: list[str] = [f for group in FIELD_GROUPS.values() for f in group]

FIELD_LABELS: dict[str, str] = {
    "cash": "Cash and cash equivalents",
    "current_assets": "Current assets",
    "total_assets": "Total assets",
    "current_liabilities": "Current liabilities",
    "total_liabilities": "Total liabilities",
    "short_term_debt": "Short-term debt (incl. current portion of LTD)",
    "long_term_debt": "Long-term debt (non-current)",
    "total_equity": "Total shareholders' equity",
    "revenue": "Revenue",
    "cost_of_revenue": "Cost of revenue",
    "gross_profit": "Gross profit",
    "ebit": "Operating income (EBIT)",
    "ebitda": "EBITDA",
    "interest_expense": "Interest expense",
    "net_income": "Net income",
    "depreciation_amortization": "Depreciation and amortization",
    "operating_cash_flow": "Operating cash flow",
    "capex": "Capital expenditures",
    "investing_cash_flow": "Investing cash flow",
    "financing_cash_flow": "Financing cash flow",
}


class FinancialPeriod(BaseModel):
    fiscal_year: int
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    filing_date: Optional[date] = None
    form_type: Optional[str] = None      # "10-K", "10-K/A", None for PDF/manual
    is_annual: bool = True
    currency: str = "USD"                # ISO code: USD, EUR, GBP, MAD ...
    original_units: Units = Units.UNITS

    # Balance sheet
    cash: FinancialValue = Field(default_factory=FinancialValue)
    current_assets: FinancialValue = Field(default_factory=FinancialValue)
    total_assets: FinancialValue = Field(default_factory=FinancialValue)
    current_liabilities: FinancialValue = Field(default_factory=FinancialValue)
    total_liabilities: FinancialValue = Field(default_factory=FinancialValue)
    short_term_debt: FinancialValue = Field(default_factory=FinancialValue)
    long_term_debt: FinancialValue = Field(default_factory=FinancialValue)
    total_equity: FinancialValue = Field(default_factory=FinancialValue)
    # Income statement
    revenue: FinancialValue = Field(default_factory=FinancialValue)
    cost_of_revenue: FinancialValue = Field(default_factory=FinancialValue)
    gross_profit: FinancialValue = Field(default_factory=FinancialValue)
    ebit: FinancialValue = Field(default_factory=FinancialValue)
    ebitda: FinancialValue = Field(default_factory=FinancialValue)
    interest_expense: FinancialValue = Field(default_factory=FinancialValue)
    net_income: FinancialValue = Field(default_factory=FinancialValue)
    depreciation_amortization: FinancialValue = Field(default_factory=FinancialValue)
    # Cash flow statement
    operating_cash_flow: FinancialValue = Field(default_factory=FinancialValue)
    capex: FinancialValue = Field(default_factory=FinancialValue)
    investing_cash_flow: FinancialValue = Field(default_factory=FinancialValue)
    financing_cash_flow: FinancialValue = Field(default_factory=FinancialValue)

    def get(self, field: str) -> Optional[float]:
        """Value of a field in full units, or None if missing."""
        return getattr(self, field).value

    def missing_fields(self) -> list[str]:
        return [f for f in ALL_FIELDS if self.get(f) is None]


class CompanyInfo(BaseModel):
    name: str
    ticker: Optional[str] = None
    cik: Optional[str] = None            # 10-digit zero-padded
    sic_code: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    reporting_framework: Optional[str] = None  # "US GAAP", "IFRS", ...
    is_financial_institution: bool = False     # banks/insurers: unsupported by scoring


class CompanyFinancials(BaseModel):
    company: CompanyInfo
    source_type: SourceType
    periods: list[FinancialPeriod] = Field(default_factory=list)  # NEWEST FIRST
    warnings: list[str] = Field(default_factory=list)

    def latest(self) -> Optional[FinancialPeriod]:
        return self.periods[0] if self.periods else None

    def period(self, fiscal_year: int) -> Optional[FinancialPeriod]:
        return next((p for p in self.periods if p.fiscal_year == fiscal_year), None)


class CompanyMatch(BaseModel):
    name: str
    ticker: Optional[str] = None
    cik: str
    match_score: float = 0.0             # 0..1, for ranking only


class DataAvailability(str, Enum):
    AVAILABLE = "available"
    COMPANY_NOT_FOUND = "company_not_found"
    NO_FINANCIAL_STATEMENTS = "no_financial_statements"
    INSUFFICIENT_DATA = "insufficient_data"
    API_UNAVAILABLE = "api_unavailable"   # outage/timeout: NOT proof that data is missing
    RATE_LIMITED = "rate_limited"


class PublicDataResult(BaseModel):
    status: DataAvailability
    financials: Optional[CompanyFinancials] = None
    message: str = ""                    # plain-English explanation for the UI


class ValidationIssue(BaseModel):
    level: Literal["error", "warning", "info"]
    message: str
    field: Optional[str] = None
    fiscal_year: Optional[int] = None


class RatioStatus(str, Enum):
    VALID = "valid"
    UNAVAILABLE = "unavailable"          # an input is missing
    UNDEFINED = "undefined"              # inputs exist but the ratio is not meaningful
                                         # (zero/negative denominator, sign problem ...)


class RatioResult(BaseModel):
    key: str                             # e.g. "current_ratio"
    label: str                           # e.g. "Current Ratio"
    category: Literal["liquidity", "leverage", "profitability",
                      "coverage", "cash_flow", "growth"]
    fiscal_year: int
    value: Optional[float] = None
    status: RatioStatus
    unit: Literal["x", "%", "currency"]
    formula: str                         # e.g. "Current Assets / Current Liabilities"
    inputs: dict[str, Optional[float]] = Field(default_factory=dict)
    explanation: str = ""                # why unavailable/undefined, or a caveat


class FactorScore(BaseModel):
    factor: Literal["liquidity", "leverage", "profitability", "coverage", "cash_flow"]
    max_points: float
    points: Optional[float] = None       # None = could not be scored (missing data)
    ratios_used: list[str] = Field(default_factory=list)
    explanation: str = ""


class CreditScore(BaseModel):
    total: Optional[float] = None        # None when data is insufficient
    category: Optional[str] = None       # e.g. "Moderate Indicative Financial Risk"
    sufficient_data: bool
    factors: list[FactorScore] = Field(default_factory=list)
    explanation: str = ""


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskAlert(BaseModel):
    alert_type: Literal["liquidity", "leverage", "coverage",
                        "profitability", "cash_flow", "trend", "data_quality"]
    title: str
    severity: Severity
    indicator: str                       # ratio key, e.g. "current_ratio"
    measured_value: Optional[float] = None
    threshold: str                       # human-readable rule, e.g. "< 1.0x"
    interpretation: str
    fiscal_year: int
    source_reference: Optional[str] = None


class AnalysisResult(BaseModel):
    financials: CompanyFinancials
    ratios: dict[int, dict[str, RatioResult]]  # fiscal_year -> ratio key -> result
    score: CreditScore
    alerts: list[RiskAlert] = Field(default_factory=list)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)
