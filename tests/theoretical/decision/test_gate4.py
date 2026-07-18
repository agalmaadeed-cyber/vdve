from theoretical.decision.gate4 import compute_gate4_verdict
from theoretical.decision.cycle_record import build_cycle_record
from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.stress_tests.engine import StressTestResult

MANDATORY_FIELDS = ("A1", "B1", "C1", "F1", "F2", "E2", "E3")


def _current_dossier(version=2, break_mandatory=False):
    fields = {code: "CONFIRMED" for code in MANDATORY_FIELDS}
    if break_mandatory:
        fields["A1"] = "UNKNOWN"
    return {
        "dossier_id": "DS-TEST",
        "version": version,
        "sections": {
            "s": {
                code.lower(): {"field_code": code, "evidence_label": label}
                for code, label in fields.items()
            }
        },
    }


def _clean_pwc_record():
    return {
        "cycle_record_id": "cr-pwc-1",
        "dossier_id": "DS-TEST",
        "dossier_version": 2,
        "claim_field_codes": ["A1", "B1"],
        "unknown_field_codes": ["C4"],
        "approved_parameters": {"price_per_unit": {"value": 49.0, "evidence_label": "FOUNDER_OPINION"}},
        "stress_test_results": [
            {"test_id": "ST-01", "status": "COMPLETED", "outcome": "SURVIVES", "target_hypothesis_id": None},
            {"test_id": "GEN-A1", "status": "COMPLETED", "outcome": None, "target_hypothesis_id": "A1"},
        ],
        "kill_status": "No concern",
        "ceiling_result": {"ceiling": "Pass with Conditions", "triggered_by": []},
        "recommendation": {
            "outcome": "Pass with Conditions",
            "payload": {"conditions": [{"hypothesis_id": "C4", "condition": "resolve the unknown"}]},
        },
    }


def _clean_advance_record():
    return {
        "cycle_record_id": "cr-adv-1",
        "dossier_id": "DS-TEST",
        "dossier_version": 2,
        "claim_field_codes": ["A1", "B1"],
        "unknown_field_codes": [],
        "approved_parameters": {"price_per_unit": {"value": 49.0, "evidence_label": "FOUNDER_OPINION"}},
        "stress_test_results": [
            {"test_id": "ST-01", "status": "COMPLETED", "outcome": "SURVIVES", "target_hypothesis_id": None},
        ],
        "kill_status": "No concern",
        "ceiling_result": {"ceiling": "Advance", "triggered_by": []},
        "recommendation": {
            "outcome": "Advance",
            "payload": {"advance_confirmation": True},
        },
    }


def test_all_nine_pass_on_clean_pass_with_conditions_record():
    verdict = compute_gate4_verdict(_clean_pwc_record(), _current_dossier())
    assert verdict["result"] == "PASS"
    assert all(c["passed"] for c in verdict["checks"])
    assert verdict["reason_codes"] == []
    assert verdict["block_routes_to"] is None


def test_all_nine_pass_on_clean_advance_record():
    verdict = compute_gate4_verdict(_clean_advance_record(), _current_dossier())
    assert verdict["result"] == "PASS"
    assert all(c["passed"] for c in verdict["checks"])
    assert verdict["block_routes_to"] is None


def test_criterion_1_outcome_reject_blocks_defense_in_depth_not_short_circuited():
    record = _clean_pwc_record()
    record["recommendation"] = {"outcome": "Reject", "payload": {"decisive_evidence": []}}
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert verdict["reason_codes"] == ["outcome_in_advance_range"]
    # every check still computed, not short-circuited
    assert len(verdict["checks"]) == 9


def test_criterion_2_stale_version_behind_current_blocks():
    record = _clean_pwc_record()
    record["dossier_version"] = 1
    verdict = compute_gate4_verdict(record, _current_dossier(version=2))
    assert verdict["result"] == "BLOCK"
    assert "version_current" in verdict["reason_codes"]


def test_criterion_3_current_dossier_mandatory_field_now_unknown_blocks_even_if_record_looks_clean():
    # This is the "re-verify against CURRENT state, not the frozen one" case --
    # the cycle record itself is untouched/clean.
    record = _clean_pwc_record()
    verdict = compute_gate4_verdict(record, _current_dossier(break_mandatory=True))
    assert verdict["result"] == "BLOCK"
    assert "mandatory_passed_current" in verdict["reason_codes"]


def test_criterion_4_condition_references_hypothesis_not_in_pool_blocks():
    record = _clean_pwc_record()
    record["recommendation"]["payload"]["conditions"].append(
        {"hypothesis_id": "GHOST", "condition": "does not exist"}
    )
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert verdict["reason_codes"] == ["conditions_reference_real_hypotheses"]


def test_criterion_5_advance_record_with_a_stored_breaks_result_blocks():
    # Can only happen if the record was hand-constructed inconsistently with what
    # compute_ceiling would allow -- exactly the re-derivation doctrine's purpose:
    # never trust, always re-check even the "impossible" case.
    record = _clean_advance_record()
    record["stress_test_results"][0]["outcome"] = "BREAKS"
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert verdict["reason_codes"] == ["no_breaks_if_advance"]


def test_criterion_6_incomplete_stress_test_blocks():
    record = _clean_pwc_record()
    record["stress_test_results"].append(
        {"test_id": "ST-99", "status": "FAILED", "outcome": None, "target_hypothesis_id": None}
    )
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert "all_tests_completed" in verdict["reason_codes"]


def test_criterion_7_open_kill_criteria_alert_blocks():
    record = _clean_pwc_record()
    record["kill_status"] = "Possible match (unconfirmed)"
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert verdict["reason_codes"] == ["no_open_kill_alert"]


def test_criterion_8_orphaned_generated_test_target_blocks():
    record = _clean_pwc_record()
    record["stress_test_results"].append(
        {"test_id": "GEN-X", "status": "COMPLETED", "outcome": None, "target_hypothesis_id": "ZZZ"}
    )
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert verdict["reason_codes"] == ["full_chain_referential_consistency"]


def test_criterion_9_advance_with_one_unknown_present_blocks():
    record = _clean_advance_record()
    record["unknown_field_codes"] = ["C4"]
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert verdict["reason_codes"] == ["unknowns_accounted_for"]


def test_criterion_9_pass_with_conditions_unknown_not_referenced_by_any_condition_blocks():
    record = _clean_pwc_record()
    # C4 is the only unknown, but the sole condition references A1, not C4.
    record["recommendation"]["payload"]["conditions"] = [{"hypothesis_id": "A1", "condition": "x"}]
    verdict = compute_gate4_verdict(record, _current_dossier())
    assert verdict["result"] == "BLOCK"
    assert verdict["reason_codes"] == ["unknowns_accounted_for"]


def test_block_routes_to_is_identical_regardless_of_which_criterion_failed():
    record_1 = _clean_pwc_record()
    record_1["recommendation"] = {"outcome": "Reject", "payload": {"decisive_evidence": []}}
    verdict_1 = compute_gate4_verdict(record_1, _current_dossier())

    record_7 = _clean_pwc_record()
    record_7["kill_status"] = "Possible match (unconfirmed)"
    verdict_7 = compute_gate4_verdict(record_7, _current_dossier())

    expected = {"outcome": "Hold", "hold_origin": "gate_procedural"}
    assert verdict_1["block_routes_to"] == expected
    assert verdict_7["block_routes_to"] == expected


def test_block_routes_to_is_none_on_pass():
    verdict = compute_gate4_verdict(_clean_pwc_record(), _current_dossier())
    assert verdict["block_routes_to"] is None


def test_integration_build_cycle_record_and_compute_gate4_verdict_compose_end_to_end():
    # Reuses Packet #8/#9's own fixture style (real compute_ceiling +
    # recommend_outcome calls, not hand-built dicts) to prove the two new
    # modules in this packet actually compose, not just pass in isolation.
    from theoretical.decision.ceiling import compute_ceiling
    from theoretical.decision.outcome import recommend_outcome

    # Mirrors test_outcome.py::test_recommend_outcome_happy_path_pass_with_conditions
    # and test_ceiling.py::test_stress_breaks_caps_at_pass_with_conditions almost
    # verbatim -- reusing Packet #8/#9's own fixture pattern rather than inventing a
    # new one. Zero unknowns deliberately: recommend_outcome's own grounding
    # validator only accepts hypothesis_id refs from claims_ranked/stress test ids
    # (theoretical/decision/outcome.py's valid_refs), never from unknowns_ranked --
    # so a real LLM_RECOMMENDED condition can never reference an unknown directly,
    # and Gate 4's own criterion 9 (Amendment A1) is trivially satisfied when there
    # are no unknowns to account for.
    claim = Hypothesis(
        dossier_id="DS-TEST", dossier_version=2, source_field="A1",
        source_section="opportunity", source_subfield="x",
        original_evidence_label="ESTIMATE", raw_dossier_text="raw",
        hypothesis_type="claim", statement="stmt", phrasing_status="PHRASED",
        risk_score=5, uncertainty_score=1, rank_score=5, rank=1,
        adjustment_status="FAILED", dependent_fields=[], adjustment_rationale=None,
    )
    stress_results = [
        StressTestResult(test_id="ST-04", test_type="quantitative_shock", category="pricing",
                          source="fixed_library", status="COMPLETED", outcome="BREAKS"),
    ]

    ceiling_result = compute_ceiling([], stress_results, kill_match_confirmed=False, kill_match_detected=False)
    assert ceiling_result["ceiling"] == "Pass with Conditions"

    def fake_llm(payload):
        return '{"outcome": "Pass with Conditions", "narrative": "ST-04 breaks but A1 is testable in field.", ' \
               '"conditions": [{"hypothesis_id": "A1", "condition": "Validate demand via 20 field interviews."}]}'

    recommendation = recommend_outcome(ceiling_result, [claim], stress_results, llm_call=fake_llm)
    assert recommendation["status"] == "LLM_RECOMMENDED"

    dossier = {"dossier_id": "DS-TEST", "version": 2}
    approved_parameters = {"price_per_unit": {"value": 49.0, "evidence_label": "FOUNDER_OPINION"}}

    cycle_record = build_cycle_record(
        dossier, [claim], [], approved_parameters, stress_results,
        kill_status="No concern", ceiling_result=ceiling_result, recommendation=recommendation,
    )

    verdict = compute_gate4_verdict(cycle_record, _current_dossier(version=2))
    assert verdict["result"] == "PASS"
    assert verdict["reason_codes"] == []
    assert verdict["chain_fingerprint"]["cycle_record_id"] == cycle_record["cycle_record_id"]
