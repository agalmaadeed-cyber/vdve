from theoretical.decision.ceiling import compute_ceiling
from theoretical.stress_tests.engine import StressTestResult


def _shock(test_id, outcome, status="COMPLETED"):
    return StressTestResult(
        test_id=test_id, test_type="quantitative_shock", category="cost",
        source="fixed_library", status=status, outcome=outcome,
    )


def test_no_triggers_gives_advance_ceiling():
    result = compute_ceiling([], [], kill_match_confirmed=False, kill_match_detected=False)
    assert result == {"ceiling": "Advance", "triggered_by": []}


def test_kill_match_confirmed_is_absolute_reject_regardless_of_everything_else():
    result = compute_ceiling([], [], kill_match_confirmed=True, kill_match_detected=True)
    assert result["ceiling"] == "Reject"


def test_kill_match_detected_unconfirmed_caps_at_hold():
    result = compute_ceiling([], [], kill_match_confirmed=False, kill_match_detected=True)
    assert result["ceiling"] == "Hold"


def test_unknowns_present_caps_at_pass_with_conditions():
    from theoretical.hypothesis_extraction.scanner import Hypothesis

    unknown = Hypothesis(
        dossier_id="DS-TEST", dossier_version=1, source_field="C4",
        source_section="solution", source_subfield="usage",
        original_evidence_label="UNKNOWN", raw_dossier_text="",
        hypothesis_type="unknown", statement=None, phrasing_status="PENDING",
        risk_score=None, uncertainty_score=None, rank_score=None, rank=None,
        adjustment_status=None, dependent_fields=[], adjustment_rationale=None,
    )
    result = compute_ceiling([unknown], [], kill_match_confirmed=False, kill_match_detected=False)
    assert result["ceiling"] == "Pass with Conditions"


def test_stress_breaks_caps_at_pass_with_conditions():
    result = compute_ceiling([], [_shock("ST-04", "BREAKS")], False, False)
    assert result["ceiling"] == "Pass with Conditions"
    assert "Pass with Conditions:stress_test_breaks:ST-04" in result["triggered_by"]


def test_stress_not_evaluable_caps_at_pass_with_conditions():
    # Reproduces Packet #6/#7's real founder-data finding: ST-03/ST-06 are
    # NOT_EVALUABLE, not BREAKS -- must still cap the ceiling, not pass silently.
    result = compute_ceiling([], [_shock("ST-03", "NOT_EVALUABLE")], False, False)
    assert result["ceiling"] == "Pass with Conditions"


def test_stress_failed_status_caps_at_pass_with_conditions():
    result = compute_ceiling([], [_shock("GEN-A1", None, status="FAILED")], False, False)
    assert result["ceiling"] == "Pass with Conditions"


def test_most_restrictive_trigger_wins_over_all_others():
    result = compute_ceiling(
        [object()],  # non-empty unknowns list (Pass with Conditions trigger)
        [_shock("ST-04", "BREAKS")],  # another Pass with Conditions trigger
        kill_match_confirmed=False,
        kill_match_detected=True,  # Hold trigger
    )
    assert result["ceiling"] == "Hold"  # Hold beats Pass with Conditions
    assert len(result["triggered_by"]) == 3  # all three recorded, not just the winner


def test_reproduces_ds_0fe02838_real_founder_data():
    # Packet #6/#7's own verified live-data outcomes: 0 unknowns, but
    # ST-01/02/04/05 BREAKS and ST-03/06 NOT_EVALUABLE -- every one of
    # the six fixed tests triggers a Pass-with-Conditions cap.
    real_results = [
        _shock("ST-01", "BREAKS"), _shock("ST-02", "BREAKS"),
        _shock("ST-03", "NOT_EVALUABLE"), _shock("ST-04", "BREAKS"),
        _shock("ST-05", "BREAKS"), _shock("ST-06", "NOT_EVALUABLE"),
    ]
    result = compute_ceiling([], real_results, kill_match_confirmed=False, kill_match_detected=False)
    assert result["ceiling"] == "Pass with Conditions"
    assert len(result["triggered_by"]) == 6
