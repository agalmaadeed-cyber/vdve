import json
from pathlib import Path

from theoretical.dossier_versioning.readiness import compute_readiness

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def test_readiness_matches_ds_0fe02838_recorded_values():
    with open(FIXTURES_DIR / "DS-0FE02838.json", encoding="utf-8") as f:
        dossier = json.load(f)

    result = compute_readiness(dossier, now="2026-07-17T00:00:00+00:00")

    assert result["score_weighted"] == 46
    assert result["score_percentage"] == 100
    assert result["mandatory_passed"] is True
    assert result["mandatory_missing"] == []
    assert result["unknown_fields"] == []
    assert result["status"] == "ready"


def test_readiness_matches_ds_synth_partial_predicted_values():
    with open(FIXTURES_DIR / "DS-SYNTH-PARTIAL.json", encoding="utf-8") as f:
        dossier = json.load(f)

    result = compute_readiness(dossier, now="2026-07-17T00:00:00+00:00")

    assert result["score_weighted"] == 39
    assert result["score_percentage"] == 85
    assert result["mandatory_passed"] is False
    assert result["mandatory_missing"] == ["B1"]
    assert set(result["unknown_fields"]) == {"C4", "A3", "D5", "B6", "B1"}
    assert result["status"] == "not_ready"
