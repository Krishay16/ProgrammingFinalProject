"""Tests for the SYNTHETIC fixtures in tests/fixtures/sample_data.py."""
import pytest

from src.models import ALL_FIELDS, CompanyFinancials, SourceType, Units
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials


def test_sample_builds_and_is_labelled_synthetic():
    f = make_sample_financials()
    assert "SYNTHETIC" in f.company.name
    assert f.source_type == SourceType.SYNTHETIC
    assert len(f.periods) == 3


def test_periods_are_newest_first():
    years = [p.fiscal_year for p in make_sample_financials().periods]
    assert years == [2024, 2023, 2022]
    assert years == sorted(years, reverse=True)


def test_sample_has_every_field_filled_with_synthetic_provenance():
    for p in make_sample_financials().periods:
        assert p.missing_fields() == []
        assert p.original_units == Units.MILLIONS
        for field in ALL_FIELDS:
            prov = getattr(p, field).provenance
            assert prov.source_type == SourceType.SYNTHETIC
            assert prov.source_ref == "tests/fixtures/sample_data.py"
            assert prov.note == "SYNTHETIC demo data"


def test_values_stored_in_full_units():
    p = make_sample_financials().latest()
    assert p.get("revenue") == 9_000_000_000.0


def test_balance_sheet_identity_holds_exactly():
    for p in make_sample_financials().periods:
        assert p.get("total_assets") == p.get("total_liabilities") + p.get("total_equity")


def test_gross_profit_identity_holds_exactly():
    for p in make_sample_financials().periods:
        assert p.get("gross_profit") == p.get("revenue") - p.get("cost_of_revenue")


def test_ebitda_is_ebit_plus_da():
    for p in make_sample_financials().periods:
        assert p.get("ebitda") == p.get("ebit") + p.get("depreciation_amortization")


def test_incomplete_fixture_gaps_are_none_not_zero():
    p = make_incomplete_financials().latest()
    expected_missing = {"interest_expense", "short_term_debt", "operating_cash_flow",
                        "capex", "investing_cash_flow", "financing_cash_flow"}
    assert set(p.missing_fields()) == expected_missing
    for field in expected_missing:
        assert p.get(field) is None


def test_incomplete_fixture_has_negative_equity():
    f = make_incomplete_financials()
    assert len(f.periods) == 1
    assert f.latest().get("total_equity") < 0
    assert "SYNTHETIC" in f.company.name


@pytest.mark.parametrize("maker", [make_sample_financials, make_incomplete_financials])
def test_json_round_trip(maker):
    f = maker()
    again = CompanyFinancials.model_validate_json(f.model_dump_json())
    assert again == f
