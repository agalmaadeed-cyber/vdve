from theoretical.decision.outcome import recommend_outcome, verify_decision_acceptance
from theoretical.stress_tests.engine import StressTestResult
from theoretical.hypothesis_extraction.scanner import Hypothesis


def _claim(field, statement="stmt", rank_score=5):
    return Hypothesis(
        dossier_id="DS-TEST", dossier_version=1, source_field=field,
        source_section="opportunity", source_subfield="x",
        original_evidence_label="ESTIMATE", raw_dossier_text="raw",
        hypothesis_type="claim", statement=statement, phrasing_status="PHRASED",
        risk_score=5, uncertainty_score=1, rank_score=rank_score, rank=1,
        adjustment_status="FAILED", dependent_fields=[], adjustment_rationale=None,
    )


def _test_result(test_id, outcome="BREAKS"):
    return StressTestResult(
        test_id=test_id, test_type="quantitative_shock", category="cost",
        source="fixed_library", status="COMPLETED", outcome=outcome,
    )


def test_recommend_outcome_happy_path_pass_with_conditions():
    ceiling_result = {"ceiling": "Pass with Conditions", "triggered_by": ["Pass with Conditions:stress_test_breaks:ST-04"]}
    claims = [_claim("A1")]
    tests = [_test_result("ST-04")]

    def fake_llm(payload):
        return '{"outcome": "Pass with Conditions", "narrative": "ST-04 breaks but A1 is testable in field.", ' \
               '"conditions": [{"hypothesis_id": "A1", "condition": "Validate demand via 20 field interviews."}]}'

    result = recommend_outcome(ceiling_result, claims, tests, llm_call=fake_llm)
    assert result["status"] == "LLM_RECOMMENDED"
    assert result["outcome"] == "Pass with Conditions"
    assert result["payload"]["conditions"][0]["hypothesis_id"] == "A1"


def test_recommend_outcome_rejects_outcome_more_optimistic_than_ceiling():
    ceiling_result = {"ceiling": "Hold", "triggered_by": ["Hold:kill_criteria_possible_match_unconfirmed"]}
    claims = [_claim("A1")]
    tests = []

    def fake_llm(payload):
        # LLM tries to recommend Advance while ceiling is Hold -- must be rejected.
        return '{"outcome": "Advance", "narrative": "looks fine", "advance_confirmation": true}'

    result = recommend_outcome(ceiling_result, claims, tests, llm_call=fake_llm)
    assert result["status"] == "FALLBACK_REJECT"
    assert result["outcome"] == "Reject"


def test_recommend_outcome_falls_back_on_ungrounded_reference():
    ceiling_result = {"ceiling": "Advance", "triggered_by": []}
    claims = [_claim("A1")]
    tests = []

    def fake_llm(payload):
        return '{"outcome": "Pass with Conditions", "narrative": "x", ' \
               '"conditions": [{"hypothesis_id": "DOES-NOT-EXIST", "condition": "y"}]}'

    result = recommend_outcome(ceiling_result, claims, tests, llm_call=fake_llm)
    assert result["status"] == "FALLBACK_REJECT"


def test_recommend_outcome_falls_back_on_llm_exception_uses_ceiling_triggers_as_evidence():
    ceiling_result = {"ceiling": "Pass with Conditions", "triggered_by": ["Pass with Conditions:stress_test_not_evaluable:ST-03"]}

    def failing_llm(payload):
        raise RuntimeError("network error")

    result = recommend_outcome(ceiling_result, [], [], llm_call=failing_llm)
    assert result["status"] == "FALLBACK_REJECT"
    assert result["outcome"] == "Reject"  # per this packet's §0 -- always Reject, never the ceiling
    assert result["payload"]["decisive_evidence"] == ["Pass with Conditions:stress_test_not_evaluable:ST-03"]


def test_recommend_outcome_advance_happy_path():
    ceiling_result = {"ceiling": "Advance", "triggered_by": []}
    claims = [_claim("A1")]
    tests = [_test_result("ST-01", outcome="SURVIVES")]

    def fake_llm(payload):
        return '{"outcome": "Advance", "narrative": "Nothing broke.", "advance_confirmation": true}'

    result = recommend_outcome(ceiling_result, claims, tests, llm_call=fake_llm)
    assert result["status"] == "LLM_RECOMMENDED"
    assert result["outcome"] == "Advance"


def test_recommend_outcome_can_be_more_conservative_than_ceiling():
    # ceiling allows Advance, but the LLM chooses to be more cautious -- always legal.
    ceiling_result = {"ceiling": "Advance", "triggered_by": []}

    def fake_llm(payload):
        return '{"outcome": "Hold", "narrative": "Prefer more field evidence first.", ' \
               '"reevaluation_conditions": "Re-run after 3 more customer interviews."}'

    result = recommend_outcome(ceiling_result, [], [], llm_call=fake_llm)
    assert result["status"] == "LLM_RECOMMENDED"
    assert result["outcome"] == "Hold"


def test_verify_decision_acceptance_valid_case():
    ceiling_result = {"ceiling": "Pass with Conditions", "triggered_by": []}
    recommendation = {
        "outcome": "Pass with Conditions", "status": "LLM_RECOMMENDED",
        "narrative": "x", "payload": {"conditions": [{"hypothesis_id": "A1", "condition": "test it"}]},
        "allowed_range": {"floor": "Reject", "ceiling": "Pass with Conditions"},
    }
    result = verify_decision_acceptance(recommendation, ceiling_result, valid_refs={"A1"})
    assert result == {"valid": True, "failures": []}


def test_verify_decision_acceptance_catches_ceiling_mismatch():
    ceiling_result = {"ceiling": "Hold", "triggered_by": []}
    recommendation = {
        "outcome": "Reject", "status": "FALLBACK_REJECT", "narrative": None,
        "payload": {"decisive_evidence": []},
        "allowed_range": {"floor": "Reject", "ceiling": "Advance"},  # mismatch on purpose
    }
    result = verify_decision_acceptance(recommendation, ceiling_result, valid_refs=set())
    assert result["valid"] is False
    assert any("does not match" in f for f in result["failures"])


def test_verify_decision_acceptance_catches_bad_grounding_ref():
    ceiling_result = {"ceiling": "Pass with Conditions", "triggered_by": []}
    recommendation = {
        "outcome": "Pass with Conditions", "status": "LLM_RECOMMENDED", "narrative": "x",
        "payload": {"conditions": [{"hypothesis_id": "GHOST", "condition": "test it"}]},
        "allowed_range": {"floor": "Reject", "ceiling": "Pass with Conditions"},
    }
    result = verify_decision_acceptance(recommendation, ceiling_result, valid_refs={"A1"})
    assert result["valid"] is False


def test_full_pipeline_reproduces_ds_0fe02838_real_founder_data():
    # Integration test: Packet #8's own verified ceiling for the real
    # founder data (Pass with Conditions, 6 triggers) feeds directly
    # into recommend_outcome + verify_decision_acceptance.
    from theoretical.decision.ceiling import compute_ceiling

    real_results = [
        _test_result("ST-01"), _test_result("ST-02"),
        StressTestResult(test_id="ST-03", test_type="quantitative_shock", category="founder",
                          source="fixed_library", status="COMPLETED", outcome="NOT_EVALUABLE"),
        _test_result("ST-04"), _test_result("ST-05"),
        StressTestResult(test_id="ST-06", test_type="quantitative_shock", category="founder",
                          source="fixed_library", status="COMPLETED", outcome="NOT_EVALUABLE"),
    ]
    ceiling_result = compute_ceiling([], real_results, kill_match_confirmed=False, kill_match_detected=False)
    assert ceiling_result["ceiling"] == "Pass with Conditions"

    def fake_llm(payload):
        return '{"outcome": "Pass with Conditions", "narrative": "Fragile margin, needs field validation.", ' \
               '"conditions": [{"hypothesis_id": "ST-04", "condition": "Test willingness to pay at a higher price point."}]}'

    recommendation = recommend_outcome(ceiling_result, [], real_results, llm_call=fake_llm)
    assert recommendation["status"] == "LLM_RECOMMENDED"

    valid_refs = {r.test_id for r in real_results}
    acceptance = verify_decision_acceptance(recommendation, ceiling_result, valid_refs)
    assert acceptance["valid"] is True
