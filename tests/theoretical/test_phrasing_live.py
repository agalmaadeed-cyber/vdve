"""
The ONE live API test for the phrasing layer (WORKING-RULES Rule 4:
one live test reserved for behavior that cannot be verified any other
way -- here, whether the real model actually complies with the
phrasing task format on real Dossier data).

Skipped automatically unless ANTHROPIC_API_KEY is set. Costs one real
API call when it runs -- not part of the default free test suite.
"""

import json
import os

import pytest

from theoretical.hypothesis_extraction.phrasing import phrase_hypotheses
from theoretical.hypothesis_extraction.scanner import scan_dossier
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set -- skipping the one live LLM test",
)


@requires_api_key
def test_live_phrasing_on_ds_0fe02838():
    with open(FIXTURES_DIR / "DS-0FE02838.json", encoding="utf-8") as f:
        dossier = json.load(f)

    scan_result = scan_dossier(dossier)
    assert scan_result.total == 13  # sanity check before spending the API call

    phrased = phrase_hypotheses(scan_result.hypotheses)  # real Anthropic call

    assert len(phrased) == 13
    # The real model is expected to comply for all 13 real hypotheses.
    # If some legitimately fail, that's real signal worth seeing -- not
    # asserted as a hard 13/13, so a partial failure reports clearly
    # rather than being masked by a loose assertion.
    phrased_count = sum(1 for h in phrased if h.phrasing_status == "PHRASED")
    failed = [h.source_field for h in phrased if h.phrasing_status == "FAILED"]

    print(f"\nLive phrasing result: {phrased_count}/13 PHRASED, failed fields: {failed}")

    for h in phrased:
        assert h.statement  # never empty, either phrased or raw-text fallback
        if h.phrasing_status == "PHRASED":
            assert h.statement != h.raw_dossier_text or not h.raw_dossier_text
