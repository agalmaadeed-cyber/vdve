from theoretical.stress_tests.engine import (
    run_quantitative_shock,
    run_all_fixed_tests,
    run_qualitative_probe,
    generate_test_specs,
)
from theoretical.stress_tests.fixed_library import FIXED_TESTS


def _params(**overrides):
    base = {
        "price_per_unit": {"value": 10.0, "evidence_label": "ESTIMATE"},
        "variable_cost_per_unit": {"value": 4.0, "evidence_label": "ESTIMATE"},
        "CAC": {"value": 5.0, "evidence_label": "ASSUMPTION"},
        "avg_customer_lifetime_months": {"value": 12.0, "evidence_label": "ESTIMATE"},
        "monthly_burn": {"value": 2000.0, "evidence_label": "ESTIMATE"},
        "budget": {"value": 20000.0, "evidence_label": "CONFIRMED"},
    }
    for k, v in overrides.items():
        base[k] = v
    return base


def test_fixed_library_has_six_tests_one_per_independent():
    shocked_params = {t["shocked_param"] for t in FIXED_TESTS}
    assert len(FIXED_TESTS) == 6
    assert shocked_params == {
        "price_per_unit", "variable_cost_per_unit", "CAC",
        "avg_customer_lifetime_months", "monthly_burn", "budget",
    }


def test_shock_survives_on_healthy_baseline():
    # CAC doubles to 10; LTV = (10-4)*12 = 72; LTV_to_CAC = 7.2 -- well above degraded_ceiling 3.0
    spec = next(t for t in FIXED_TESTS if t["test_id"] == "ST-01")
    result = run_quantitative_shock(spec, _params())
    assert result.outcome == "SURVIVES"
    assert result.status == "COMPLETED"


def test_shock_breaks_on_fragile_margin():
    # variable_cost_per_unit +30% -> 5.2 vs price 10 -> gross_margin 0.48, still fine;
    # use a near-zero-margin baseline instead to force BREAKS.
    spec = next(t for t in FIXED_TESTS if t["test_id"] == "ST-05")
    params = _params(
        price_per_unit={"value": 5.0, "evidence_label": "ESTIMATE"},
        variable_cost_per_unit={"value": 4.5, "evidence_label": "ESTIMATE"},
    )
    result = run_quantitative_shock(spec, params)
    # variable_cost -> 4.5*1.3=5.85 > price 5.0 -> negative margin
    assert result.outcome == "BREAKS"


def test_shock_not_evaluable_reproduces_founder_live_run():
    # Real case from the founder's own first export (2026-07-16):
    # budget=0, monthly_burn=0 -> runway_months is None, not a crash,
    # not silently compared against a threshold.
    spec = next(t for t in FIXED_TESTS if t["test_id"] == "ST-03")
    params = _params(
        budget={"value": 0.0, "evidence_label": "FOUNDER_OPINION"},
        monthly_burn={"value": 0.0, "evidence_label": "FOUNDER_OPINION"},
    )
    result = run_quantitative_shock(spec, params)
    assert result.outcome == "NOT_EVALUABLE"
    assert result.metric_value is None
    assert result.status == "COMPLETED"  # ran correctly; the math is genuinely undefined


def test_shock_missing_shocked_param_stays_none_not_invented():
    spec = next(t for t in FIXED_TESTS if t["test_id"] == "ST-01")
    params = _params(CAC={"value": None, "evidence_label": "UNKNOWN"})
    result = run_quantitative_shock(spec, params)
    assert result.metric_value is None
    assert result.outcome == "NOT_EVALUABLE"


def test_run_all_fixed_tests_returns_six_results():
    results = run_all_fixed_tests(_params())
    assert len(results) == 6
    assert {r.test_id for r in results} == {t["test_id"] for t in FIXED_TESTS}


def test_qualitative_probe_happy_path():
    spec = {
        "test_id": "GEN-A1", "category": "demand",
        "target_hypothesis_id": "A1", "statement": "Managers face recurring chaos.",
        "raw_text": "raw", "overlaps_with_fixed": ["ST-02"],
    }

    def fake_llm(s):
        return '{"hypothesis_id": "A1", "severity": "MEDIUM", "rationale": "Grounded in raw_text about recurring chaos."}'

    result = run_qualitative_probe(spec, llm_call=fake_llm)
    assert result.status == "COMPLETED"
    assert result.severity == "MEDIUM"
    assert result.overlaps_with_fixed == ["ST-02"]


def test_qualitative_probe_degrades_on_identity_mismatch():
    spec = {
        "test_id": "GEN-A1", "category": "demand",
        "target_hypothesis_id": "A1", "statement": "x", "raw_text": "x",
        "overlaps_with_fixed": [],
    }

    def fake_llm(s):
        return '{"hypothesis_id": "WRONG", "severity": "LOW", "rationale": "not grounded to A1"}'

    result = run_qualitative_probe(spec, llm_call=fake_llm)
    assert result.status == "FAILED"
    assert result.severity is None


def test_qualitative_probe_degrades_on_llm_exception():
    def failing_llm(s):
        raise RuntimeError("network error")

    spec = {
        "test_id": "GEN-A1", "category": "demand",
        "target_hypothesis_id": "A1", "statement": "x", "raw_text": "x",
        "overlaps_with_fixed": [],
    }
    result = run_qualitative_probe(spec, llm_call=failing_llm)
    assert result.status == "FAILED"


def test_generate_test_specs_uses_source_field_as_identity():
    from theoretical.hypothesis_extraction.scanner import Hypothesis

    h = Hypothesis(
        dossier_id="DS-TEST", dossier_version=1, source_field="D3",
        source_section="business_model", source_subfield="pricing",
        original_evidence_label="ESTIMATE", raw_dossier_text="raw",
        hypothesis_type="claim", statement="stmt", phrasing_status="PHRASED",
        risk_score=4, uncertainty_score=1, rank_score=4, rank=1,
        adjustment_status="FAILED", dependent_fields=[], adjustment_rationale=None,
    )
    specs = generate_test_specs([h], n=3)
    assert len(specs) == 1
    assert specs[0]["target_hypothesis_id"] == "D3"
    assert specs[0]["category"] == "pricing"  # section D -> pricing
    assert specs[0]["overlaps_with_fixed"]  # ST-04 is also "pricing"
