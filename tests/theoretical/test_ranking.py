"""
Acceptance tests for the ranking module (P1.0.3). All deterministic,
zero API cost -- the fixture-based tests use llm_call=None (this
packet's actual delivered mode); the governance tests stub raw LLM
responses directly against apply_risk_adjustment(), same pattern as
Packet #2's phrasing guard tests.
"""

import json
from pathlib import Path

from theoretical.hypothesis_extraction.ranking import (
    apply_risk_adjustment,
    compute_base_risk_score,
    compute_uncertainty_score,
    rank_hypotheses,
)
from theoretical.hypothesis_extraction.scanner import Hypothesis, scan_dossier

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _hyp(field_code, hypothesis_type="claim", label="ESTIMATE"):
    return Hypothesis(
        dossier_id="DS-TEST",
        dossier_version=1,
        source_field=field_code,
        source_section="test",
        source_subfield="test",
        original_evidence_label=label,
        raw_dossier_text="raw",
        hypothesis_type=hypothesis_type,
    )


# --- Real-fixture acceptance numbers, verified by Cowork before handoff ---

def test_ds_0fe02838_claim_order_matches_registered_expectation():
    dossier = _load_fixture("DS-0FE02838.json")
    scan_result = scan_dossier(dossier)
    claims, unknowns = rank_hypotheses(scan_result.hypotheses, llm_call=None)

    assert [h.source_field for h in claims] == [
        "B6", "A1", "A3", "B1", "F3", "F4", "D3", "D4", "D5", "D6", "C1", "C2", "C4",
    ]
    assert [h.rank_score for h in claims] == [10, 5, 5, 5, 5, 5, 4, 4, 4, 4, 3, 3, 3]
    assert unknowns == []  # DS-0FE02838 has zero unknown-type hypotheses
    assert claims[0].rank == 1 and claims[-1].rank == 13


def test_ds_synth_partial_claim_and_unknown_order_matches_registered_expectation():
    dossier = _load_fixture("DS-SYNTH-PARTIAL.json")
    scan_result = scan_dossier(dossier)
    claims, unknowns = rank_hypotheses(scan_result.hypotheses, llm_call=None)

    assert [h.source_field for h in claims] == [
        "A1", "F3", "F4", "D3", "D4", "D6", "C1", "C2",
    ]
    assert [h.source_field for h in unknowns] == ["A3", "B1", "B6", "D5", "C4"]
    assert [h.rank_score for h in unknowns] == [15, 15, 15, 12, 9]
    assert unknowns[0].rank == 1 and unknowns[-1].rank == 5


# --- Deterministic component checks ---

def test_uncertainty_score_mapping():
    assert compute_uncertainty_score(_hyp("A1", label="ESTIMATE")) == 1
    assert compute_uncertainty_score(_hyp("A1", label="ASSUMPTION")) == 2
    assert compute_uncertainty_score(_hyp("A1", label="FOUNDER_OPINION")) == 2
    assert compute_uncertainty_score(_hyp("A1", label="UNKNOWN")) == 3


def test_base_risk_score_by_section():
    expected = {"A": 5, "B": 5, "C": 3, "D": 4, "E": 3, "F": 5}
    for section, weight in expected.items():
        assert compute_base_risk_score(_hyp(f"{section}1")) == weight


# --- P1.0.3(b) adjustment governance ---

def test_valid_adjustment_applied_and_clamped_within_range():
    hyps = [_hyp("A1"), _hyp("B1")]
    response = json.dumps(
        [{"field_code": "A1", "adjustment": 1, "dependent_fields": ["B1"], "rationale": "depends on B1"}]
    )
    result = apply_risk_adjustment(hyps, response)
    by_field = {h.source_field: h for h in result}
    assert by_field["A1"].risk_score == 5 + 1  # base 5, +1
    assert by_field["A1"].adjustment_status == "APPLIED"
    assert by_field["A1"].dependent_fields == ["B1"]
    assert by_field["B1"].adjustment_status == "FAILED"  # no entry for B1 -> base only


def test_adjustment_clamped_in_code_even_if_llm_proposes_more():
    hyps = [_hyp("A1"), _hyp("B1")]
    response = json.dumps(
        [{"field_code": "A1", "adjustment": 5, "dependent_fields": ["B1"], "rationale": "big swing"}]
    )
    result = apply_risk_adjustment(hyps, response)
    a1 = next(h for h in result if h.source_field == "A1")
    assert a1.risk_score == 5 + 1  # clamped to +1, not +5


def test_missing_dependent_fields_rejected():
    hyps = [_hyp("A1")]
    response = json.dumps([{"field_code": "A1", "adjustment": 1, "dependent_fields": [], "rationale": "no dep"}])
    result = apply_risk_adjustment(hyps, response)
    assert result[0].adjustment_status == "FAILED"
    assert result[0].risk_score == 5  # base, unadjusted


def test_self_referencing_dependent_field_rejected():
    hyps = [_hyp("A1")]
    response = json.dumps(
        [{"field_code": "A1", "adjustment": 1, "dependent_fields": ["A1"], "rationale": "depends on itself"}]
    )
    result = apply_risk_adjustment(hyps, response)
    assert result[0].adjustment_status == "FAILED"  # self-reference is not a valid dependency


def test_missing_rationale_rejected():
    hyps = [_hyp("A1"), _hyp("B1")]
    response = json.dumps([{"field_code": "A1", "adjustment": 1, "dependent_fields": ["B1"], "rationale": "   "}])
    result = apply_risk_adjustment(hyps, response)
    assert result[0].adjustment_status == "FAILED"


def test_dependent_field_not_in_input_rejected():
    hyps = [_hyp("A1")]
    response = json.dumps(
        [{"field_code": "A1", "adjustment": 1, "dependent_fields": ["Z9"], "rationale": "depends on Z9"}]
    )
    result = apply_risk_adjustment(hyps, response)
    assert result[0].adjustment_status == "FAILED"  # Z9 doesn't exist in this hypothesis set


def test_malformed_json_all_fail_to_base_weight():
    hyps = [_hyp("A1"), _hyp("C1")]
    result = apply_risk_adjustment(hyps, "not json {{{")
    by_field = {h.source_field: h for h in result}
    assert by_field["A1"].risk_score == 5 and by_field["A1"].adjustment_status == "FAILED"
    assert by_field["C1"].risk_score == 3 and by_field["C1"].adjustment_status == "FAILED"


def test_rank_hypotheses_with_no_llm_call_is_fully_deterministic_baseline():
    hyps = [_hyp("A1"), _hyp("B1", hypothesis_type="unknown", label="UNKNOWN")]
    claims, unknowns = rank_hypotheses(hyps, llm_call=None)
    assert claims[0].adjustment_status == "FAILED"  # no LLM call attempted -> base weight only
    assert claims[0].risk_score == 5
    assert unknowns[0].risk_score == 5
    assert unknowns[0].uncertainty_score == 3


def test_deterministic_tie_break_is_reproducible():
    """Same input, run twice, must produce byte-identical order."""
    dossier = _load_fixture("DS-0FE02838.json")
    scan_result = scan_dossier(dossier)
    claims_1, _ = rank_hypotheses(scan_result.hypotheses, llm_call=None)
    claims_2, _ = rank_hypotheses(scan_result.hypotheses, llm_call=None)
    assert [h.source_field for h in claims_1] == [h.source_field for h in claims_2]
