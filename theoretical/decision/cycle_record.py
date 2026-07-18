"""
Theoretical Cycle Record construction (P1.0.8's missing artifact --
see this packet's §0(a)). A frozen, timestamped snapshot of one
decision run's inputs and outputs. Pure, storage-agnostic -- returns
a dict, writes nothing. The UI packet (#17) is responsible for
keeping a list of these in session state; this function only builds
one given the current pipeline outputs.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.stress_tests.engine import StressTestResult


def build_cycle_record(
    dossier: dict,
    claims_ranked: list[Hypothesis],
    unknowns_ranked: list[Hypothesis],
    approved_parameters: dict,
    stress_results: list[StressTestResult],
    kill_status: str,
    ceiling_result: dict,
    recommendation: dict,
    now: str | None = None,
) -> dict:
    """
    Returns a TheoreticalCycleRecord dict:
      {"cycle_record_id": str, "dossier_id": str, "dossier_version": int,
       "claim_field_codes": [str, ...], "unknown_field_codes": [str, ...],
       "approved_parameters": dict, "stress_test_results": [dict, ...],
       "kill_status": str, "ceiling_result": dict, "recommendation": dict,
       "created_at": str}

    Every field is a plain copy of an already-computed pipeline output
    -- this function invents nothing, calls no LLM, makes no decision.
    It only freezes what already exists at the moment it's called.
    """
    return {
        "cycle_record_id": str(uuid.uuid4()),
        "dossier_id": dossier.get("dossier_id"),
        "dossier_version": dossier.get("version", 1),
        "claim_field_codes": [h.source_field for h in claims_ranked],
        "unknown_field_codes": [h.source_field for h in unknowns_ranked],
        "approved_parameters": approved_parameters,
        "stress_test_results": [asdict(r) for r in stress_results],
        "kill_status": kill_status,
        "ceiling_result": ceiling_result,
        "recommendation": recommendation,
        "created_at": now or datetime.now(timezone.utc).isoformat(),
    }
