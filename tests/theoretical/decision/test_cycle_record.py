from theoretical.decision.cycle_record import build_cycle_record
from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.stress_tests.engine import StressTestResult


def _hyp(field, hypothesis_type="claim"):
    return Hypothesis(
        dossier_id="DS-TEST", dossier_version=2, source_field=field,
        source_section="opportunity", source_subfield="x",
        original_evidence_label="ESTIMATE", raw_dossier_text="raw",
        hypothesis_type=hypothesis_type,
    )


def _stress(test_id, outcome="SURVIVES"):
    return StressTestResult(
        test_id=test_id, test_type="quantitative_shock", category="cost",
        source="fixed_library", status="COMPLETED", outcome=outcome,
    )


def _build(now=None):
    dossier = {"dossier_id": "DS-TEST", "version": 2}
    claims = [_hyp("A1"), _hyp("B1")]
    unknowns = [_hyp("C4", hypothesis_type="unknown")]
    approved_parameters = {"price_per_unit": {"value": 49.0, "evidence_label": "FOUNDER_OPINION"}}
    stress_results = [_stress("ST-01"), _stress("ST-04", outcome="BREAKS")]
    kill_status = "No concern"
    ceiling_result = {"ceiling": "Pass with Conditions", "triggered_by": ["Pass with Conditions:stress_test_breaks:ST-04"]}
    recommendation = {
        "outcome": "Pass with Conditions", "status": "LLM_RECOMMENDED", "narrative": "x",
        "payload": {"conditions": [{"hypothesis_id": "C4", "condition": "test it"}]},
        "allowed_range": {"floor": "Reject", "ceiling": "Pass with Conditions"},
    }
    return build_cycle_record(
        dossier, claims, unknowns, approved_parameters, stress_results,
        kill_status, ceiling_result, recommendation, now=now,
    )


def test_all_fields_land_correctly_from_given_inputs():
    record = _build(now="2026-07-19T00:00:00+00:00")

    assert record["dossier_id"] == "DS-TEST"
    assert record["dossier_version"] == 2
    assert record["claim_field_codes"] == ["A1", "B1"]
    assert record["unknown_field_codes"] == ["C4"]
    assert record["approved_parameters"] == {"price_per_unit": {"value": 49.0, "evidence_label": "FOUNDER_OPINION"}}
    assert record["stress_test_results"][0]["test_id"] == "ST-01"
    assert record["stress_test_results"][1]["outcome"] == "BREAKS"
    assert record["kill_status"] == "No concern"
    assert record["ceiling_result"]["ceiling"] == "Pass with Conditions"
    assert record["recommendation"]["outcome"] == "Pass with Conditions"
    assert record["created_at"] == "2026-07-19T00:00:00+00:00"
    assert "cycle_record_id" in record


def test_cycle_record_id_is_unique_across_two_calls():
    first = _build()
    second = _build()
    assert first["cycle_record_id"] != second["cycle_record_id"]


def test_created_at_accepts_injected_now_for_determinism():
    record = _build(now="2026-01-01T12:00:00+00:00")
    assert record["created_at"] == "2026-01-01T12:00:00+00:00"


def test_created_at_defaults_to_a_real_timestamp_when_not_injected():
    record = _build()
    assert record["created_at"] is not None
    assert "T" in record["created_at"]
