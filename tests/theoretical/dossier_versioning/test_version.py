import json
from pathlib import Path

from theoretical.dossier_versioning.version import build_new_version

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def _load(name):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def test_reformulation_resets_target_field_to_unknown():
    dossier = _load("DS-0FE02838.json")
    trigger = {"type": "reformulation", "reformulation_targets": [
        {"field": "D3", "guidance": "Re-examine pricing after a 20-customer pilot."}
    ]}
    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")
    new_dossier = result["dossier"]

    d3 = next(
        f for sec in new_dossier["sections"].values() for f in sec.values() if f.get("field_code") == "D3"
    )
    assert d3["evidence_label"] == "UNKNOWN"
    assert d3["value"] == ""
    assert result["dossier"]["change_log"][0]["field"] == "D3"
    assert result["dossier"]["change_log"][0]["trigger"] == "reformulation"
    assert result["rejected_changes"] == []


def test_reformulation_never_mutates_input_dossier():
    dossier = _load("DS-0FE02838.json")
    original_d3_label = next(
        f for sec in dossier["sections"].values() for f in sec.values() if f.get("field_code") == "D3"
    )["evidence_label"]

    build_new_version(dossier, {"type": "reformulation", "reformulation_targets": [{"field": "D3", "guidance": "x"}]})

    current_d3_label = next(
        f for sec in dossier["sections"].values() for f in sec.values() if f.get("field_code") == "D3"
    )["evidence_label"]
    assert current_d3_label == original_d3_label  # unchanged -- input never mutated


def test_version_identity_stamped_correctly():
    dossier = _load("DS-0FE02838.json")
    result = build_new_version(dossier, {"type": "reformulation", "reformulation_targets": []})
    new_dossier = result["dossier"]
    assert new_dossier["version"] == dossier["version"] + 1
    assert new_dossier["version_origin"] == "vdve"
    assert new_dossier["derived_from_version"] == dossier["version"]


def test_reformulating_mandatory_field_drops_mandatory_passed_readiness_interlock():
    # P1.0.7c's readiness interlock: reformulating a mandatory field
    # (B1) to UNKNOWN must immediately flip mandatory_passed to False.
    dossier = _load("DS-0FE02838.json")
    result = build_new_version(
        dossier, {"type": "reformulation", "reformulation_targets": [{"field": "B1", "guidance": "Re-validate payer."}]}
    )
    assert result["dossier"]["readiness"]["mandatory_passed"] is False
    assert "B1" in result["dossier"]["readiness"]["mandatory_missing"]


def test_evidence_update_applies_fresh_value_and_label_not_unknown():
    dossier = _load("DS-SYNTH-PARTIAL.json")  # has UNKNOWN fields to upgrade
    trigger = {"type": "evidence_update", "updates": [
        {"field": "B1", "new_value": "Small business owners in the UAE, confirmed via 5 interviews.",
         "new_evidence_label": "CONFIRMED", "source": "Founder field interviews, 2026-07-18"}
    ]}
    result = build_new_version(dossier, trigger, now="2026-07-18T00:00:00+00:00")
    new_dossier = result["dossier"]

    b1 = next(
        f for sec in new_dossier["sections"].values() for f in sec.values() if f.get("field_code") == "B1"
    )
    assert b1["evidence_label"] == "CONFIRMED"
    assert "Founder field interviews, 2026-07-18" in b1["sources"]
    # B1 was the mandatory-missing field in DS-SYNTH-PARTIAL -- confirming it now passes:
    assert new_dossier["readiness"]["mandatory_passed"] is True


def test_unresolvable_field_reference_is_rejected_not_invented():
    dossier = _load("DS-0FE02838.json")
    trigger = {"type": "reformulation", "reformulation_targets": [{"field": "Z9-DOES-NOT-EXIST", "guidance": "x"}]}
    result = build_new_version(dossier, trigger)
    assert result["rejected_changes"] == [{"field": "Z9-DOES-NOT-EXIST", "reason": "field_code not found in dossier"}]
    assert result["dossier"]["change_log"] == []


def test_illegal_trigger_type_raises():
    dossier = _load("DS-0FE02838.json")
    import pytest
    with pytest.raises(ValueError):
        build_new_version(dossier, {"type": "not_a_real_trigger"})
