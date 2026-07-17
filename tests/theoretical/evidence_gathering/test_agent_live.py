"""
Reserved live API test for the evidence gathering agent (WORKING-RULES
Rule 4: one live test reserved per LLM-touching module for behavior
that cannot be verified any other way -- here, whether the real model
+ Anthropic's hosted web_search tool actually comply with the
evidence-search task format on real Dossier data, and whether the
block-ordering assumption flagged in Packet #12 §0(b) holds (that the
LAST text block in the response content list is the structured JSON
answer, even after interleaved server_tool_use/web_search_tool_result
blocks).

Skipped automatically unless ANTHROPIC_API_KEY is set. Costs one real
API call (with mandatory web search) when it runs -- not part of the
default free test suite.
"""

import json
import os
from pathlib import Path

import pytest

from theoretical.evidence_gathering.agent import gather_evidence
from theoretical.hypothesis_extraction.scanner import scan_dossier

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set -- skipping the live evidence-search LLM test",
)


@requires_api_key
def test_live_evidence_search_on_ds_0fe02838():
    with open(FIXTURES_DIR / "DS-0FE02838.json", encoding="utf-8") as f:
        dossier = json.load(f)

    scan_result = scan_dossier(dossier)
    claims = scan_result.hypotheses[:2]  # keep the live call small and cheap
    assert claims  # sanity check before spending the API call

    proposals = gather_evidence(claims, dossier_version=dossier["version"])  # real Anthropic call w/ web_search

    assert len(proposals) == len(claims)
    statuses = [(p.hypothesis_id, p.search_status) for p in proposals]
    print(f"\nLive evidence search result: {statuses}")

    for p in proposals:
        assert p.search_status in ("FOUND", "NO_EVIDENCE_FOUND", "NOT_SEARCHED")
        if p.search_status == "FOUND":
            # Grounding fields must all be present -- confirms the
            # block-ordering assumption in §0(b) held for this call.
            assert p.proposed_value
            assert p.proposed_evidence_label
            assert p.source
            assert p.citation_excerpt
