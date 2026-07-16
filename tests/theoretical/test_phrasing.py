"""
Stub-based acceptance tests for the phrasing guard layer (P1.0.2).
Zero API cost -- every test injects a canned llm_call, no network access.
"""

import json

from theoretical.hypothesis_extraction.phrasing import (
    apply_phrasing_guards,
    phrase_hypotheses,
)
from theoretical.hypothesis_extraction.scanner import Hypothesis


def _hyp(field_code: str, hypothesis_type: str = "claim", raw_text: str = "raw text") -> Hypothesis:
    return Hypothesis(
        dossier_id="DS-TEST",
        dossier_version=1,
        source_field=field_code,
        source_section="test_section",
        source_subfield="test_subfield",
        original_evidence_label="ESTIMATE",
        raw_dossier_text=raw_text,
        hypothesis_type=hypothesis_type,
    )


def test_normal_case_all_fields_phrased():
    hyps = [_hyp("A1"), _hyp("B1"), _hyp("C1")]
    response = json.dumps(
        [
            {"field_code": "A1", "statement": "Statement A1."},
            {"field_code": "B1", "statement": "Statement B1."},
            {"field_code": "C1", "statement": "Statement C1."},
        ]
    )
    result = apply_phrasing_guards(hyps, response)

    assert len(result) == 3
    assert {h.source_field for h in result} == {"A1", "B1", "C1"}
    assert all(h.phrasing_status == "PHRASED" for h in result)
    by_field = {h.source_field: h.statement for h in result}
    assert by_field["A1"] == "Statement A1."


def test_count_mismatch_missing_field_falls_back():
    hyps = [_hyp("A1"), _hyp("B1"), _hyp("C1", raw_text="C1 raw fallback")]
    response = json.dumps(
        [
            {"field_code": "A1", "statement": "Statement A1."},
            {"field_code": "B1", "statement": "Statement B1."},
            # C1 missing entirely
        ]
    )
    result = apply_phrasing_guards(hyps, response)

    assert len(result) == 3  # nothing lost
    by_field = {h.source_field: h for h in result}
    assert by_field["A1"].phrasing_status == "PHRASED"
    assert by_field["B1"].phrasing_status == "PHRASED"
    assert by_field["C1"].phrasing_status == "FAILED"
    assert by_field["C1"].statement == "C1 raw fallback"


def test_invented_field_code_dropped_never_persisted():
    hyps = [_hyp("A1")]
    response = json.dumps(
        [
            {"field_code": "A1", "statement": "Statement A1."},
            {"field_code": "Z9", "statement": "Invented, not in input."},
        ]
    )
    result = apply_phrasing_guards(hyps, response)

    assert len(result) == 1  # Z9 never appears -- not in input, not added
    assert result[0].source_field == "A1"
    assert result[0].phrasing_status == "PHRASED"


def test_malformed_json_all_fields_fail_safe():
    hyps = [_hyp("A1", raw_text="raw A1"), _hyp("B1", raw_text="raw B1")]
    response = "this is not json at all {{{"
    result = apply_phrasing_guards(hyps, response)

    assert len(result) == 2
    assert all(h.phrasing_status == "FAILED" for h in result)
    by_field = {h.source_field: h.statement for h in result}
    assert by_field["A1"] == "raw A1"
    assert by_field["B1"] == "raw B1"


def test_non_array_json_all_fields_fail_safe():
    hyps = [_hyp("A1", raw_text="raw A1")]
    response = json.dumps({"not": "an array"})
    result = apply_phrasing_guards(hyps, response)

    assert result[0].phrasing_status == "FAILED"
    assert result[0].statement == "raw A1"


def test_empty_statement_treated_as_failure():
    hyps = [_hyp("A1", raw_text="raw A1")]
    response = json.dumps([{"field_code": "A1", "statement": "   "}])
    result = apply_phrasing_guards(hyps, response)

    assert result[0].phrasing_status == "FAILED"
    assert result[0].statement == "raw A1"


def test_duplicate_field_code_first_match_wins_no_overwrite():
    hyps = [_hyp("A1")]
    response = json.dumps(
        [
            {"field_code": "A1", "statement": "First statement."},
            {"field_code": "A1", "statement": "Second statement -- should be ignored."},
        ]
    )
    result = apply_phrasing_guards(hyps, response)

    assert len(result) == 1
    assert result[0].statement == "First statement."


def test_llm_call_exception_fails_safe_not_crash():
    hyps = [_hyp("A1", raw_text="raw A1")]

    def broken_llm_call(_hypotheses):
        raise ConnectionError("simulated network failure")

    result = phrase_hypotheses(hyps, llm_call=broken_llm_call)

    assert result[0].phrasing_status == "FAILED"
    assert result[0].statement == "raw A1"


def test_output_never_mutates_input_list():
    hyps = [_hyp("A1")]
    original_statement = hyps[0].statement
    response = json.dumps([{"field_code": "A1", "statement": "New statement."}])

    apply_phrasing_guards(hyps, response)

    assert hyps[0].statement == original_statement  # input untouched
