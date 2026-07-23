import json
from pathlib import Path

from theoretical.evidence_gathering.review import build_evidence_update_trigger
from theoretical.dossier_versioning.version import build_new_version
from theoretical.hypothesis_extraction.scanner import scan_dossier

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def _load(name):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def test_approve_all_found_writes_new_version_with_change_log():
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")
    found_ids = {p["hypothesis_id"] for p in proposals if p["search_status"] == "FOUND"}

    trigger = build_evidence_update_trigger(proposals, approved_ids=found_ids)
    assert len(trigger["updates"]) == 3  # B1, B6, F4

    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")
    assert result["dossier"]["version"] == dossier["version"] + 1
    assert len(result["dossier"]["change_log"]) == 3
    assert result["rejected_changes"] == []


def test_reject_all_writes_nothing():
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")

    trigger = build_evidence_update_trigger(proposals, approved_ids=set())
    assert trigger["updates"] == []
    # Per this packet's own app.py contract (§5), the caller skips
    # build_new_version() entirely when there's nothing to apply --
    # confirmed here at the trigger-construction level: an empty
    # approved set produces an empty updates list, nothing to write.


def test_partial_approval_only_includes_approved_field():
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")

    trigger = build_evidence_update_trigger(proposals, approved_ids={"B1"})
    assert len(trigger["updates"]) == 1
    assert trigger["updates"][0]["field"] == "B1"

    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")
    new_dossier = result["dossier"]

    b1 = next(f for sec in new_dossier["sections"].values() for f in sec.values() if f.get("field_code") == "B1")
    assert b1["evidence_label"] == "CONFIRMED"
    d3 = next(f for sec in new_dossier["sections"].values() for f in sec.values() if f.get("field_code") == "D3")
    assert d3["evidence_label"] == "ESTIMATE"  # untouched -- never approved


def test_approving_non_found_proposal_id_is_a_no_op():
    proposals = _load("mock_evidence_proposals.json")
    trigger = build_evidence_update_trigger(proposals, approved_ids={"A1", "D3"})  # NO_EVIDENCE_FOUND, NOT_SEARCHED
    assert trigger["updates"] == []


def test_re_extraction_after_approval_reduces_hypothesis_count():
    # Full loop, backend-provable with zero cost (req #4): B1 upgrades
    # ESTIMATE -> CONFIRMED, so it must vanish from the NEXT
    # hypothesis-extraction pass (CONFIRMED fields never become
    # hypotheses, P1.0.2). Concrete proof that re-extraction on vN+1
    # behaves correctly, matching this packet's own app.py claim.
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")
    trigger = build_evidence_update_trigger(proposals, approved_ids={"B1"})
    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")

    original_scan = scan_dossier(dossier)
    new_scan = scan_dossier(result["dossier"])
    assert original_scan.total == 13
    assert new_scan.total == 12
    assert "B1" not in {h.source_field for h in new_scan.hypotheses}


# --- a.2 fix (cross-project evaluation, 2026-07-23): persistent mock-evidence badge ---

def test_mock_flagged_trigger_marks_every_update_is_mock_true():
    proposals = _load("mock_evidence_proposals.json")
    found_ids = {p["hypothesis_id"] for p in proposals if p["search_status"] == "FOUND"}

    trigger = build_evidence_update_trigger(proposals, approved_ids=found_ids, is_mock=True)
    assert len(trigger["updates"]) == 3
    assert all(u["is_mock"] is True for u in trigger["updates"])


def test_default_trigger_marks_every_update_is_mock_false():
    # is_mock defaults to False when the caller doesn't pass it -- covers
    # every pre-a.2 call site and the live-evidence-search path, neither
    # of which ever passes is_mock=True.
    proposals = _load("mock_evidence_proposals.json")
    found_ids = {p["hypothesis_id"] for p in proposals if p["search_status"] == "FOUND"}

    trigger = build_evidence_update_trigger(proposals, approved_ids=found_ids)
    assert all(u["is_mock"] is False for u in trigger["updates"])


def test_mock_approval_persists_is_mock_evidence_true_on_the_field():
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")
    trigger = build_evidence_update_trigger(proposals, approved_ids={"B1"}, is_mock=True)
    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")

    b1 = next(f for sec in result["dossier"]["sections"].values() for f in sec.values() if f.get("field_code") == "B1")
    assert b1["is_mock_evidence"] is True
    # change_log entry keeps the same provenance for audit/Gate-4-review purposes
    log_entry = next(c for c in result["dossier"]["change_log"] if c["field"] == "B1")
    assert log_entry["is_mock"] is True


def test_live_approval_persists_is_mock_evidence_false_on_the_field():
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")
    trigger = build_evidence_update_trigger(proposals, approved_ids={"B1"}, is_mock=False)
    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")

    b1 = next(f for sec in result["dossier"]["sections"].values() for f in sec.values() if f.get("field_code") == "B1")
    assert b1["is_mock_evidence"] is False


def test_mock_badge_survives_into_the_next_hypothesis_scan():
    # F4 stays a hypothesis after approval (ASSUMPTION label, not upgraded
    # to CONFIRMED), so it's still visible in the next scan -- the direct
    # test that the badge actually reaches what the Ranking table reads.
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")
    trigger = build_evidence_update_trigger(proposals, approved_ids={"F4"}, is_mock=True)
    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")

    new_scan = scan_dossier(result["dossier"])
    f4 = next(h for h in new_scan.hypotheses if h.source_field == "F4")
    assert f4.is_mock_evidence is True

    # every OTHER hypothesis, untouched by this approval, must stay False
    others = [h for h in new_scan.hypotheses if h.source_field != "F4"]
    assert all(h.is_mock_evidence is False for h in others)


def test_fields_never_touched_by_any_evidence_update_default_is_mock_false():
    # The original, untouched fixture Dossier has no is_mock_evidence key
    # on any field at all (pre-dates this fix) -- scan_dossier must treat
    # that absence as False, not raise or misreport.
    dossier = _load("DS-0FE02838.json")
    scan = scan_dossier(dossier)
    assert all(h.is_mock_evidence is False for h in scan.hypotheses)


def test_reformulation_clears_a_prior_mock_flag():
    # A field previously approved from mock evidence (is_mock_evidence=True)
    # that later gets reformulated (reset to blank/UNKNOWN) must not keep
    # carrying a stale mock badge for content that no longer exists.
    dossier = _load("DS-0FE02838.json")
    proposals = _load("mock_evidence_proposals.json")
    mock_trigger = build_evidence_update_trigger(proposals, approved_ids={"F4"}, is_mock=True)
    after_mock = build_new_version(dossier, mock_trigger, now="2026-07-18T00:00:00+00:00")["dossier"]
    f4_before = next(f for sec in after_mock["sections"].values() for f in sec.values() if f.get("field_code") == "F4")
    assert f4_before["is_mock_evidence"] is True

    reformulation_trigger = {"type": "reformulation", "reformulation_targets": [{"field": "F4", "guidance": "test"}]}
    after_reformulation = build_new_version(after_mock, reformulation_trigger, now="2026-07-19T00:00:00+00:00")["dossier"]
    f4_after = next(f for sec in after_reformulation["sections"].values() for f in sec.values() if f.get("field_code") == "F4")
    assert f4_after["is_mock_evidence"] is False
    assert f4_after["evidence_label"] == "UNKNOWN"
