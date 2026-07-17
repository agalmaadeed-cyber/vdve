import json
from pathlib import Path

from theoretical.decision.kill_criteria import detect_kill_criteria_match, get_kill_criteria_text

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def test_get_kill_criteria_text_extracts_f2_from_real_fixture():
    with open(FIXTURES_DIR / "DS-0FE02838.json", encoding="utf-8") as f:
        dossier = json.load(f)
    text = get_kill_criteria_text(dossier)
    assert text.strip()
    assert "6" in text  # the 6-month hard cap mentioned in F2's real content


def test_detect_returns_no_match_when_kill_text_empty_no_llm_call():
    dossier = {"sections": {}}

    def should_not_be_called(payload):
        raise AssertionError("llm_call must not be invoked when F2 is empty")

    result = detect_kill_criteria_match(dossier, [], [], llm_call=should_not_be_called)
    assert result == {"status": "COMPLETED", "possible_match": False, "rationale": None, "grounding_refs": []}


def _dossier_with_kill_text(text):
    return {"sections": {"success_definition": {"kill_criteria": {"field_code": "F2", "value": text}}}}


def test_detect_happy_path_true_match_with_valid_grounding():
    dossier = _dossier_with_kill_text("Stop if churn exceeds 50% for 2 months.")

    def fake_llm(payload):
        return json.dumps({
            "possible_match": True,
            "rationale": "ST-02 shows a lifetime shock consistent with the churn threshold in kill_criteria_text.",
            "grounding_refs": ["ST-02"],
        })

    from theoretical.stress_tests.engine import StressTestResult
    stress_results = [StressTestResult(
        test_id="ST-02", test_type="quantitative_shock", category="demand",
        source="fixed_library", status="COMPLETED", outcome="BREAKS",
    )]
    result = detect_kill_criteria_match(dossier, stress_results, [], llm_call=fake_llm)
    assert result["status"] == "COMPLETED"
    assert result["possible_match"] is True
    assert result["grounding_refs"] == ["ST-02"]


def test_detect_degrades_on_ungrounded_match_claim():
    dossier = _dossier_with_kill_text("Stop if churn exceeds 50%.")

    def fake_llm(payload):
        return json.dumps({
            "possible_match": True,
            "rationale": "seems bad",
            "grounding_refs": ["ST-99-DOES-NOT-EXIST"],
        })

    result = detect_kill_criteria_match(dossier, [], [], llm_call=fake_llm)
    assert result["status"] == "FAILED"
    assert result["possible_match"] is True  # fail-cautious, per this packet's §0


def test_detect_degrades_on_llm_exception_fail_cautious():
    dossier = _dossier_with_kill_text("Stop if churn exceeds 50%.")

    def failing_llm(payload):
        raise RuntimeError("network error")

    result = detect_kill_criteria_match(dossier, [], [], llm_call=failing_llm)
    assert result["status"] == "FAILED"
    assert result["possible_match"] is True


def test_detect_false_match_happy_path():
    dossier = _dossier_with_kill_text("Stop if churn exceeds 50%.")

    def fake_llm(payload):
        return json.dumps({
            "possible_match": False,
            "rationale": "No stress test or hypothesis indicates churn anywhere near the 50% threshold.",
            "grounding_refs": [],
        })

    result = detect_kill_criteria_match(dossier, [], [], llm_call=fake_llm)
    assert result["status"] == "COMPLETED"
    assert result["possible_match"] is False
