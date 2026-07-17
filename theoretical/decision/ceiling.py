"""
Deterministic ceiling computation (P1.0.6, Amendment A1, and this
packet's own §0 extension for NOT_EVALUABLE/FAILED stress tests).

The ceiling is the ONLY thing this module computes. It never
recommends an actual outcome -- that is Packet #9's job, bounded
strictly by the ceiling this module returns. No LLM anywhere in this
file (P1.0.6's own "the ceiling-computing layer reads exclusively
from registered artifacts" rule -- deterministic code is the actual
guarantee, never prompt compliance).

Legal permissiveness ordering, fixed by P1.0.6:
    Reject < Hold < Reformulate < Pass with Conditions < Advance
"""

from __future__ import annotations

from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.stress_tests.engine import StressTestResult

OUTCOME_ORDER: dict[str, int] = {
    "Reject": 0,
    "Hold": 1,
    "Reformulate": 2,
    "Pass with Conditions": 3,
    "Advance": 4,
}


def compute_ceiling(
    unknowns_ranked: list[Hypothesis],
    stress_results: list[StressTestResult],
    kill_match_confirmed: bool,
    kill_match_detected: bool,
) -> dict:
    """
    Returns {"ceiling": str, "triggered_by": [str, ...]}.

    "ceiling" is the single most restrictive (lowest-ordered) level
    among every triggered ceiling, or "Advance" if nothing triggered
    (a clean idea is never held back by an absent problem).
    "triggered_by" lists every individual trigger, each tagged with
    its own ceiling level and reason -- a full audit trail, not just
    the winning one, so a later review can see every concern that was
    considered even if a lower one made the others moot.
    """
    triggers: list[tuple[str, str]] = []

    if kill_match_confirmed:
        triggers.append(("Reject", "kill_criteria_confirmed_by_founder"))
    elif kill_match_detected:
        triggers.append(("Hold", "kill_criteria_possible_match_unconfirmed"))

    if unknowns_ranked:
        triggers.append(("Pass with Conditions", "unresolved_unknown_hypotheses"))

    for r in stress_results:
        if r.status == "FAILED":
            triggers.append(("Pass with Conditions", f"stress_test_failed:{r.test_id}"))
        elif r.outcome == "BREAKS":
            triggers.append(("Pass with Conditions", f"stress_test_breaks:{r.test_id}"))
        elif r.outcome == "NOT_EVALUABLE":
            triggers.append(("Pass with Conditions", f"stress_test_not_evaluable:{r.test_id}"))
        # DEGRADED and SURVIVES trigger nothing -- informational only,
        # available to Packet #9's LLM recommendation within the ceiling.

    if not triggers:
        return {"ceiling": "Advance", "triggered_by": []}

    effective_ceiling = min(triggers, key=lambda t: OUTCOME_ORDER[t[0]])[0]
    return {
        "ceiling": effective_ceiling,
        "triggered_by": [f"{level}:{reason}" for level, reason in triggers],
    }
