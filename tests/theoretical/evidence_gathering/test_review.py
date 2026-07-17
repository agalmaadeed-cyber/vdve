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
