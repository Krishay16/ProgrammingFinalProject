"""Tests for the shared data model (src/models.py)."""
from datetime import date

import pytest
from pydantic import ValidationError

from src.models import (ALL_FIELDS, FIELD_GROUPS, FIELD_LABELS, CompanyFinancials,
                        CompanyInfo, FinancialPeriod, FinancialValue, SourceType, Units)


def test_field_lists_are_consistent():
    assert len(ALL_FIELDS) == 20
    assert len(set(ALL_FIELDS)) == 20
    assert set(ALL_FIELDS) == set(FIELD_LABELS)
    assert sum(len(v) for v in FIELD_GROUPS.values()) == 20


def test_every_field_exists_on_period():
    p = FinancialPeriod(fiscal_year=2024)
    for field in ALL_FIELDS:
        assert isinstance(getattr(p, field), FinancialValue)


def test_missing_is_none_not_zero():
    p = FinancialPeriod(fiscal_year=2024)
    assert p.get("revenue") is None
    assert p.revenue.is_missing
    assert p.missing_fields() == ALL_FIELDS


def test_real_zero_is_not_missing():
    p = FinancialPeriod(fiscal_year=2024, short_term_debt=FinancialValue(value=0.0))
    assert p.get("short_term_debt") == 0.0
    assert not p.short_term_debt.is_missing
    assert "short_term_debt" not in p.missing_fields()


def test_units_values():
    assert Units.MILLIONS.value == 1_000_000
    assert Units.BILLIONS.value == 1_000_000_000


def test_company_financials_latest_and_period():
    f = CompanyFinancials(
        company=CompanyInfo(name="X"), source_type=SourceType.MANUAL,
        periods=[FinancialPeriod(fiscal_year=2024), FinancialPeriod(fiscal_year=2023)])
    assert f.latest().fiscal_year == 2024
    assert f.period(2023).fiscal_year == 2023
    assert f.period(1999) is None


def test_empty_financials_have_no_latest():
    f = CompanyFinancials(company=CompanyInfo(name="X"), source_type=SourceType.MANUAL)
    assert f.latest() is None


def test_defaults_do_not_share_state():
    a, b = FinancialPeriod(fiscal_year=2024), FinancialPeriod(fiscal_year=2023)
    a.revenue = FinancialValue(value=1.0)
    assert b.get("revenue") is None


def test_invalid_type_rejected():
    with pytest.raises(ValidationError):
        FinancialPeriod(fiscal_year="not a year")


def test_period_json_round_trip_keeps_dates():
    p = FinancialPeriod(fiscal_year=2024, period_end=date(2024, 6, 30),
                        revenue=FinancialValue(value=5.0))
    again = FinancialPeriod.model_validate_json(p.model_dump_json())
    assert again == p
    assert again.period_end == date(2024, 6, 30)
