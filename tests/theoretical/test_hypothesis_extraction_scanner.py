"""
Acceptance tests for the deterministic Hypothesis Extraction scanner.

These two tests encode the acceptance numbers registered in
phases/phase-1/phase1_decisions_log.md during P1.0.2 / P1.0.3:

    DS-0FE02838.json      -> 13 total / 13 claim / 0 unknown
    DS-SYNTH-PARTIAL.json -> 13 total /  8 claim / 5 unknown (incl. B1)

No network access, no LLM call, no external service — fully
reproducible from the two committed fixtures.
"""

import json
from pathlib import Path

from theoretical.hypothesis_extraction.scanner import scan_dossier

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def test_ds_0fe02838_matches_registered_acceptance_numbers():
    dossier = _load_fixture("DS-0FE02838.json")
    result = scan_dossier(dossier)

    assert result.total == 13
    assert result.claim_count == 13
    assert result.unknown_count == 0
    assert result.total_dossier_fields == 32
    assert set(result.excluded_fields) == {"F1", "F2"}


def test_ds_synth_partial_matches_registered_acceptance_numbers():
    dossier = _load_fixture("DS-SYNTH-PARTIAL.json")
    result = scan_dossier(dossier)

    assert result.total == 13
    assert result.claim_count == 8
    assert result.unknown_count == 5

    unknown_field_codes = {
        h.source_field for h in result.hypotheses if h.hypothesis_type == "unknown"
    }
    assert unknown_field_codes == {"C4", "A3", "D5", "B1", "B6"}
    # Edge case registered in P1.0.3: a mandatory field (B1) turned UNKNOWN
    # must still surface as an ordinary "unknown" hypothesis — no special case.
    assert "B1" in unknown_field_codes


def test_no_confirmed_field_ever_becomes_a_hypothesis():
    dossier = _load_fixture("DS-0FE02838.json")
    result = scan_dossier(dossier)
    labels = {h.original_evidence_label for h in result.hypotheses}
    assert "CONFIRMED" not in labels


def test_excluded_fields_never_appear_as_hypotheses():
    dossier = _load_fixture("DS-0FE02838.json")
    result = scan_dossier(dossier)
    hypothesis_field_codes = {h.source_field for h in result.hypotheses}
    assert "F1" not in hypothesis_field_codes
    assert "F2" not in hypothesis_field_codes


def test_every_hypothesis_is_pending_phrasing_and_unranked():
    """Packet #1 boundary check: this scanner never phrases or ranks."""
    dossier = _load_fixture("DS-0FE02838.json")
    result = scan_dossier(dossier)
    for h in result.hypotheses:
        assert h.statement is None
        assert h.phrasing_status == "PENDING"
        assert h.risk_score is None
        assert h.uncertainty_score is None
        assert h.rank is None
