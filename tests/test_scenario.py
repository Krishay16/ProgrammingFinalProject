"""Tests for src/scenario.py and src/ui/scenario_page.py. Owned by Person 4.

All data is SYNTHETIC (tests/fixtures/sample_data.py). Expected values are hand-calculated;
the arithmetic is written next to each one, in MILLIONS (values are stored x 1_000_000).

make_sample_financials() FY2024 base, in millions:
    revenue 9,000   EBIT 1,350   EBITDA 1,800 (reported)   interest 150
    debt 400 + 2,800 = 3,200   cash 1,500   equity 5,400
    current assets 4,800 / current liabilities 2,600   OCF 1,500   capex 600

Floating point: e.g. 1_350e6 * 0.8 is not guaranteed to be bit-identical to 1_080e6, so
"exact" checks use pytest.approx(rel=1e-12) (12 significant digits), never a looser bound.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src import config
from src.models import (CompanyFinancials, FinancialValue, Provenance, RatioStatus, SourceType,
                        ValueOrigin, VerificationStatus)
from src.scenario import SCENARIO_NOTE, ScenarioInputs, run_scenario
from tests.fixtures.sample_data import make_incomplete_financials, make_sample_financials

M = 1_000_000.0
EXACT = 1e-12


def approx(x: float) -> object:
    return pytest.approx(x, rel=EXACT)


def _with_latest(f: CompanyFinancials, **millions: float) -> CompanyFinancials:
    """SYNTHETIC copy of `f` with some latest-period values replaced (given in millions)."""
    out = f.model_copy(deep=True)
    for field, v in millions.items():
        getattr(out.periods[0], field).value = v * M
    return out


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------
def test_inputs_default_to_zero():
    s = ScenarioInputs()
    assert (s.revenue_change_pct, s.ebit_change_pct, s.debt_change_pct,
            s.interest_change_pct) == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize("field", ["revenue_change_pct", "ebit_change_pct",
                                   "debt_change_pct", "interest_change_pct"])
def test_inputs_bounds_inclusive(field):
    assert getattr(ScenarioInputs(**{field: -0.9}), field) == -0.9
    assert getattr(ScenarioInputs(**{field: 2.0}), field) == 2.0
    with pytest.raises(ValidationError):
        ScenarioInputs(**{field: -0.91})
    with pytest.raises(ValidationError):
        ScenarioInputs(**{field: 2.01})


# --------------------------------------------------------------------------------------
# Core behaviour requested
# --------------------------------------------------------------------------------------
def test_ebit_minus_20_gives_operating_margin_0_8x_base():
    """Revenue unchanged: margin 1,350/9,000 = 15.0% -> 1,080/9,000 = 12.0% = 0.8 x 15%."""
    r = run_scenario(make_sample_financials(), ScenarioInputs(ebit_change_pct=-0.20))
    base = r.base["operating_margin"].value
    new = r.stressed["operating_margin"].value
    assert base == approx(0.15)
    assert new == approx(0.12)
    assert new == approx(0.8 * base)
    assert r.stressed_period.get("ebit") == approx(1_080 * M)          # 1,350 x 0.8
    assert r.stressed_period.get("revenue") == 9_000 * M               # untouched


def test_original_financials_untouched():
    f = make_sample_financials()
    before = f.model_dump()
    r = run_scenario(f, ScenarioInputs(revenue_change_pct=-0.5, ebit_change_pct=-0.5,
                                       debt_change_pct=1.0, interest_change_pct=1.0))
    assert f.model_dump() == before
    assert r.stressed_period is not f.periods[0]
    # The original provenance object is not shared/mutated either.
    assert f.periods[0].ebit.provenance.origin == ValueOrigin.REPORTED


def test_debt_plus_30_raises_debt_to_equity_by_30_pct():
    """D/E 3,200/5,400 = 0.5926x -> 4,160/5,400 = 0.7704x = 1.3 x base."""
    r = run_scenario(make_sample_financials(), ScenarioInputs(debt_change_pct=0.30))
    base = r.base["debt_to_equity"].value
    new = r.stressed["debt_to_equity"].value
    assert base == approx(3_200 / 5_400)
    assert new == approx(4_160 / 5_400)
    assert new == approx(1.3 * base)
    assert r.stressed_period.get("short_term_debt") == approx(520 * M)   # 400 x 1.3
    assert r.stressed_period.get("long_term_debt") == approx(3_640 * M)  # 2,800 x 1.3
    assert r.stressed_period.get("cash") == 1_500 * M                    # cash not adjusted


def test_negative_ebit_decline_makes_loss_worse():
    """SYNTHETIC: EBIT -100, EBITDA 350 (=-100+450). EBIT -20% -> -100 - |-100| x 0.2 = -120.
    EBITDA moves by the same -20 -> 330."""
    f = _with_latest(make_sample_financials(), ebit=-100, ebitda=350)
    r = run_scenario(f, ScenarioInputs(ebit_change_pct=-0.20))
    assert r.stressed_period.get("ebit") == approx(-120 * M)
    assert r.stressed_period.get("ebitda") == approx(330 * M)
    assert any("absolute value" in a and "loss larger" in a for a in r.assumptions)
    # Operating margin worsens: -100/9,000 = -1.11% -> -120/9,000 = -1.33%
    assert r.stressed["operating_margin"].value < r.base["operating_margin"].value


def test_negative_ebit_increase_makes_loss_smaller():
    """SYNTHETIC: EBIT -100 with EBIT +20% -> -100 + 100 x 0.2 = -80."""
    f = _with_latest(make_sample_financials(), ebit=-100, ebitda=350)
    r = run_scenario(f, ScenarioInputs(ebit_change_pct=0.20))
    assert r.stressed_period.get("ebit") == approx(-80 * M)


def test_insufficient_data_case_does_not_crash():
    """make_incomplete_financials(): interest expense, OCF and capex are missing ->
    coverage and cash flow cannot be scored, before AND after the stress."""
    f = make_incomplete_financials()
    r = run_scenario(f, ScenarioInputs(ebit_change_pct=-0.20, debt_change_pct=0.30,
                                       interest_change_pct=0.50))
    for score in (r.base_score, r.stressed_score):
        assert score.total is None
        assert score.sufficient_data is False
        assert score.explanation.startswith(config.INSUFFICIENT_SCORE_LABEL)
    # Missing stays missing: never filled with 0 by the scenario.
    assert r.stressed_period.get("interest_expense") is None
    assert r.stressed_period.get("short_term_debt") is None
    assert r.stressed["interest_coverage"].status == RatioStatus.UNAVAILABLE
    # Long-term debt was present and is stressed: 1,800 x 1.3 = 2,340
    assert r.stressed_period.get("long_term_debt") == approx(2_340 * M)
    assert any("Interest expense is missing" in a for a in r.assumptions)
    assert any("Short-term debt (incl. current portion of LTD) is missing" in a
               for a in r.assumptions)


def test_no_periods_raises_clear_error():
    f = make_sample_financials().model_copy(update={"periods": []})
    with pytest.raises(ValueError, match="No financial periods"):
        run_scenario(f, ScenarioInputs(ebit_change_pct=-0.2))


# --------------------------------------------------------------------------------------
# Revenue-only shock pins the "independent shocks" simplification
# --------------------------------------------------------------------------------------
def test_revenue_cut_alone_raises_margins():
    """Revenue -10% with EBIT unchanged (documented simplification, not a realistic downside):
    operating margin 1,350/9,000 = 15.0% -> 1,350/8,100 = 16.67%
    FCF margin (1,500-600)/9,000 = 10.0% -> 900/8,100 = 11.11%
    Revenue growth 9,000/8,400-1 = 7.14% -> 8,100/8,400-1 = -3.57%
    Score unchanged at 91.875 (operating margin was already in the top band)."""
    r = run_scenario(make_sample_financials(), ScenarioInputs(revenue_change_pct=-0.10))
    assert r.stressed_period.get("revenue") == approx(8_100 * M)
    assert r.stressed_period.get("ebit") == 1_350 * M
    assert r.stressed["operating_margin"].value == approx(1_350 / 8_100)
    assert r.stressed["fcf_margin"].value == approx(900 / 8_100)
    assert r.stressed["operating_margin"].value > r.base["operating_margin"].value
    assert r.stressed["fcf_margin"].value > r.base["fcf_margin"].value
    assert r.stressed["revenue_growth"].value == approx(8_100 / 8_400 - 1)
    assert r.stressed_score.total == approx(91.875)
    assert any("shocked independently" in a and "raises operating margin" in a
               for a in r.assumptions)


# --------------------------------------------------------------------------------------
# Expected scores for the three presets (hand calculation in docs/methodology.md)
# --------------------------------------------------------------------------------------
def test_base_score_is_91_875():
    """15 (CR 1.85x) + 21.875 ((0.75+1.0)/2 x 25) + 20 (15.0%) + 20 (9.0x) + 15 (10.0%)."""
    r = run_scenario(make_sample_financials(), ScenarioInputs())
    assert r.base_score.total == approx(91.875)
    assert r.stressed_score.total == approx(91.875)       # zero shocks change nothing
    assert r.stressed_period.model_dump() == make_sample_financials().periods[0].model_dump()


@pytest.mark.parametrize("inputs, expected_total, expected_points", [
    # EBIT -20%: EBIT 1,080, EBITDA 1,530.
    #   liq 15 | lev ND/EBITDA 1,700/1,530 = 1.11x (0.75), D/E 0.59x (0.75) -> 18.75
    #   prof 12.0% (0.75) -> 15 | cov 1,080/150 = 7.2x (0.75) -> 15 | cf 10.0% -> 15
    (ScenarioInputs(ebit_change_pct=-0.20), 78.75, [15, 18.75, 15, 15, 15]),
    # Revenue -10% and EBIT -25%: revenue 8,100, EBIT 1,012.5, EBITDA 1,462.5.
    #   liq 15 | lev 1,700/1,462.5 = 1.16x (0.75), D/E 0.59x (0.75) -> 18.75
    #   prof 1,012.5/8,100 = 12.5% (0.75) -> 15 | cov 1,012.5/150 = 6.75x -> 15
    #   cf 900/8,100 = 11.1% (>= 10%) -> 15
    (ScenarioInputs(revenue_change_pct=-0.10, ebit_change_pct=-0.25), 78.75,
     [15, 18.75, 15, 15, 15]),
    # Debt +30%: debt 520 + 3,640 = 4,160.
    #   liq 15 | lev D/E 4,160/5,400 = 0.77x (0.75), ND/EBITDA (4,160-1,500)/1,800 = 1.48x
    #   (0.75) -> 18.75 | prof 15.0% -> 20 | cov 9.0x -> 20 | cf 10.0% -> 15
    (ScenarioInputs(debt_change_pct=0.30), 88.75, [15, 18.75, 20, 20, 15]),
])
def test_preset_scores(inputs, expected_total, expected_points):
    r = run_scenario(make_sample_financials(), inputs)
    assert [fs.points for fs in r.stressed_score.factors] == [approx(x)
                                                              for x in expected_points]
    assert r.stressed_score.total == approx(expected_total)


def test_preset_categories():
    f = make_sample_financials()
    assert run_scenario(f, ScenarioInputs()).base_score.category == \
        "Lower Indicative Financial Risk"                                   # 91.875 >= 80
    assert run_scenario(f, ScenarioInputs(ebit_change_pct=-0.2)).stressed_score.category == \
        "Moderate Indicative Financial Risk"                                # 60 <= 78.75 < 80
    assert run_scenario(f, ScenarioInputs(debt_change_pct=0.3)).stressed_score.category == \
        "Lower Indicative Financial Risk"                                   # 88.75 >= 80


# --------------------------------------------------------------------------------------
# Provenance, label, assumptions
# --------------------------------------------------------------------------------------
def test_changed_values_are_derived_with_note_unchanged_values_are_not():
    r = run_scenario(make_sample_financials(), ScenarioInputs(ebit_change_pct=-0.2,
                                                              debt_change_pct=0.3))
    p = r.stressed_period
    for field in ("ebit", "ebitda", "short_term_debt", "long_term_debt"):
        prov = getattr(p, field).provenance
        assert prov.origin == ValueOrigin.DERIVED, field
        assert prov.note == SCENARIO_NOTE, field
        assert prov.verification == VerificationStatus.UNVERIFIED, field
        assert prov.original_text is None, field
    for field in ("revenue", "interest_expense", "cash", "total_equity"):
        assert getattr(p, field).provenance.origin == ValueOrigin.REPORTED, field


def test_stressed_value_provenance_is_derived_unverified():
    """SYNTHETIC EBIT with SEC-style provenance; EBIT -20%: 1,350 -> 1,080.
    The stressed copy must not claim to be a matched source fact; the input is untouched."""
    f = make_sample_financials().model_copy(deep=True)
    f.periods[0].ebit = FinancialValue(
        value=1_350 * M,
        provenance=Provenance(source_type=SourceType.SEC_EDGAR, source_ref="SYNTHETIC ref",
                              location="SYNTHETIC 10-K", tag="OperatingIncomeLoss",
                              verification=VerificationStatus.SOURCE_STRUCTURED,
                              original_text="1,350"))
    r = run_scenario(f, ScenarioInputs(ebit_change_pct=-0.20))

    stressed = r.stressed_period.ebit
    assert stressed.value == approx(1_080 * M)
    prov = stressed.provenance
    assert prov.origin == ValueOrigin.DERIVED
    assert prov.verification == VerificationStatus.UNVERIFIED
    assert prov.original_text is None
    assert prov.note == SCENARIO_NOTE
    assert prov.source_type == SourceType.SEC_EDGAR      # traceability kept
    assert prov.source_ref == "SYNTHETIC ref"
    assert prov.location == "SYNTHETIC 10-K"
    assert prov.tag == "OperatingIncomeLoss"

    orig = f.periods[0].ebit.provenance
    assert orig.verification == VerificationStatus.SOURCE_STRUCTURED
    assert orig.original_text == "1,350"
    assert orig.origin == ValueOrigin.REPORTED
    assert f.periods[0].ebit.value == 1_350 * M


def test_ebitda_not_reported_is_left_missing_and_derived_by_engine():
    """SYNTHETIC: EBITDA missing -> stays None; net debt / EBITDA uses EBIT + D&A:
    (1,080 + 450) = 1,530 -> 1,700 / 1,530."""
    f = make_sample_financials()
    f.periods[0].ebitda.value = None
    r = run_scenario(f, ScenarioInputs(ebit_change_pct=-0.2))
    assert r.stressed_period.get("ebitda") is None
    assert r.stressed["net_debt_to_ebitda"].value == approx(1_700 / 1_530)
    assert any("EBITDA is not reported" in a for a in r.assumptions)


def test_label_and_assumptions():
    r = run_scenario(make_sample_financials(), ScenarioInputs(ebit_change_pct=-0.2))
    assert r.label == config.SCENARIO_LABEL
    text = " ".join(r.assumptions)
    assert "EBIT -20%" in text
    assert "Cash, equity" in text and "not adjusted" in text


def test_financial_institution_scores_insufficient():
    f = make_sample_financials()
    f.company.is_financial_institution = True
    r = run_scenario(f, ScenarioInputs(ebit_change_pct=-0.2))
    assert r.base_score.total is None and r.stressed_score.total is None
    assert r.stressed_score.explanation == config.FINANCIAL_INSTITUTION_MESSAGE


# --------------------------------------------------------------------------------------
# Page (headless Streamlit AppTest, offline)
# --------------------------------------------------------------------------------------
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _scenario_page_with_demo():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    next(b for b in at.sidebar.button if "SYNTHETIC" in b.label).click().run()
    at.sidebar.radio[0].set_value("Stress Scenario").run()
    return at


def test_page_without_data_explains_and_offers_search():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Stress Scenario").run()
    assert not at.exception
    assert any("No confirmed financial data" in i.value for i in at.info)
    assert any(b.label == "Go to Search" for b in at.button)


def test_page_with_demo_data_and_preset():
    at = _scenario_page_with_demo()
    assert not at.exception and not at.error
    assert any(config.SCENARIO_LABEL in w.value for w in at.warning)
    assert len(at.slider) == 4
    next(b for b in at.button if b.label == "EBIT -20%").click().run()
    assert not at.exception and not at.error
    values = {s.label: s.value for s in at.slider}
    assert values["EBIT change (%)"] == -20 and values["Revenue change (%)"] == 0
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Reported score (FY2024)"] == "91.875 / 100"
    assert metrics["Stressed scenario score"] == "78.75 / 100"
