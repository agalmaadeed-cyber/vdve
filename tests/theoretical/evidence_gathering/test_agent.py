import json

from theoretical.evidence_gathering.agent import gather_evidence
from theoretical.hypothesis_extraction.scanner import Hypothesis


def _hyp(field, statement="stmt"):
    return Hypothesis(
        dossier_id="DS-TEST", dossier_version=2, source_field=field,
        source_section="opportunity", source_subfield="x",
        original_evidence_label="ESTIMATE", raw_dossier_text="raw",
        hypothesis_type="claim", statement=statement, phrasing_status="PHRASED",
        risk_score=5, uncertainty_score=1, rank_score=5, rank=1,
        adjustment_status="FAILED", dependent_fields=[], adjustment_rationale=None,
    )


def test_found_happy_path_grounded():
    def fake_llm(hyps):
        return json.dumps([{
            "hypothesis_id": "A1", "search_status": "FOUND",
            "proposed_value": "62% of SMB managers report tool fragmentation as a top pain point.",
            "proposed_evidence_label": "ESTIMATE",
            "source": "https://example.com/smb-survey-2026",
            "citation_excerpt": "62% of respondents cited fragmented tools as their top productivity complaint.",
        }])

    result = gather_evidence([_hyp("A1")], dossier_version=2, llm_call=fake_llm, now="2026-07-18T00:00:00+00:00")
    assert len(result) == 1
    assert result[0].search_status == "FOUND"
    assert result[0].proposed_evidence_label == "ESTIMATE"
    assert result[0].dossier_version == 2


def test_no_evidence_found_happy_path():
    def fake_llm(hyps):
        return json.dumps([{"hypothesis_id": "A1", "search_status": "NO_EVIDENCE_FOUND"}])

    result = gather_evidence([_hyp("A1")], dossier_version=2, llm_call=fake_llm)
    assert result[0].search_status == "NO_EVIDENCE_FOUND"
    assert result[0].proposed_value is None


def test_ungrounded_found_degrades_to_not_searched_not_no_evidence():
    def fake_llm(hyps):
        return json.dumps([{
            "hypothesis_id": "A1", "search_status": "FOUND",
            "proposed_value": "some finding", "proposed_evidence_label": "CONFIRMED",
            "source": "", "citation_excerpt": "",  # missing source/excerpt -- ungrounded
        }])

    result = gather_evidence([_hyp("A1")], dossier_version=2, llm_call=fake_llm)
    assert result[0].search_status == "NOT_SEARCHED"  # per this packet's §0(a), never NO_EVIDENCE_FOUND


def test_invalid_evidence_label_degrades_to_not_searched():
    def fake_llm(hyps):
        return json.dumps([{
            "hypothesis_id": "A1", "search_status": "FOUND",
            "proposed_value": "x", "proposed_evidence_label": "UNKNOWN",  # not a valid proposed label
            "source": "https://example.com", "citation_excerpt": "quote",
        }])

    result = gather_evidence([_hyp("A1")], dossier_version=2, llm_call=fake_llm)
    assert result[0].search_status == "NOT_SEARCHED"


def test_missing_hypothesis_in_response_becomes_not_searched():
    def fake_llm(hyps):
        return json.dumps([])  # says nothing about A1 at all

    result = gather_evidence([_hyp("A1")], dossier_version=2, llm_call=fake_llm)
    assert result[0].search_status == "NOT_SEARCHED"


def test_total_call_failure_all_not_searched():
    def failing_llm(hyps):
        raise RuntimeError("network error")

    result = gather_evidence([_hyp("A1"), _hyp("A3")], dossier_version=2, llm_call=failing_llm)
    assert all(r.search_status == "NOT_SEARCHED" for r in result)


def test_identity_guard_ignores_invented_hypothesis_id():
    def fake_llm(hyps):
        return json.dumps([
            {"hypothesis_id": "A1", "search_status": "NO_EVIDENCE_FOUND"},
            {"hypothesis_id": "GHOST-NOT-IN-INPUT", "search_status": "FOUND",
             "proposed_value": "x", "proposed_evidence_label": "CONFIRMED",
             "source": "y", "citation_excerpt": "z"},
        ])

    result = gather_evidence([_hyp("A1")], dossier_version=2, llm_call=fake_llm)
    assert len(result) == 1  # the invented entry never surfaces as a second result
    assert result[0].hypothesis_id == "A1"
    assert result[0].search_status == "NO_EVIDENCE_FOUND"


def test_duplicate_hypothesis_id_first_match_wins():
    def fake_llm(hyps):
        return json.dumps([
            {"hypothesis_id": "A1", "search_status": "FOUND",
             "proposed_value": "first", "proposed_evidence_label": "ESTIMATE",
             "source": "s1", "citation_excerpt": "e1"},
            {"hypothesis_id": "A1", "search_status": "NO_EVIDENCE_FOUND"},  # duplicate, ignored
        ])

    result = gather_evidence([_hyp("A1")], dossier_version=2, llm_call=fake_llm)
    assert result[0].search_status == "FOUND"
    assert result[0].proposed_value == "first"


def test_every_input_hypothesis_appears_exactly_once():
    def fake_llm(hyps):
        return json.dumps([{"hypothesis_id": "A1", "search_status": "NO_EVIDENCE_FOUND"}])
        # A3 and B6 never mentioned -- must still appear as NOT_SEARCHED

    result = gather_evidence([_hyp("A1"), _hyp("A3"), _hyp("B6")], dossier_version=2, llm_call=fake_llm)
    assert len(result) == 3
    statuses = {r.hypothesis_id: r.search_status for r in result}
    assert statuses == {"A1": "NO_EVIDENCE_FOUND", "A3": "NOT_SEARCHED", "B6": "NOT_SEARCHED"}
