"""
LLM recommendation bounded by Packet #8's deterministic ceiling
(P1.0.6 points 1 and 4).

The ceiling (theoretical.decision.ceiling.compute_ceiling) is computed
BEFORE this module runs and is never recomputed or second-guessed
here -- this module's only job is choosing WHICH outcome within
[Reject, ceiling] best fits the evidence, and building that outcome's
mandatory structured payload. The LLM is free to be more conservative
than the ceiling; it is never allowed to exceed it, enforced here in
code (clamp-in-code doctrine, same as every prior packet), not
trusted from the prompt.

Any validation failure -- unparseable JSON, an outcome outside the
allowed range, a missing/malformed payload field, or a grounding
reference that doesn't resolve to a real artifact -- degrades
deterministically to a system-generated Reject. See this packet's
own §0 for the full rationale on why the fallback is always Reject,
never the ceiling itself.
"""

from __future__ import annotations

import json
import os
from typing import Callable

from theoretical.decision.ceiling import OUTCOME_ORDER
from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.llm_utils import strip_json_markdown_fence
from theoretical.stress_tests.engine import StressTestResult

RECOMMENDATION_SYSTEM_PROMPT = """You recommend one theoretical-decision outcome for a venture idea, bounded by a ceiling already computed deterministically by the system -- you may choose that ceiling outcome or any MORE conservative one, never a more optimistic one.

Legal ordering (most to least conservative): Reject < Hold < Reformulate < Pass with Conditions < Advance.

You will receive one JSON object: {"ceiling": str, "ceiling_reasons": [str, ...], "claims": [{"hypothesis_id": str, "statement": str, "rank_score": number|null}], "unknowns": [{"hypothesis_id": str, "statement": str}], "stress_tests": [{"test_id": str, "outcome_or_severity": str, "category": str}]}.

"unknowns" are hypotheses with no current answer -- if the ceiling is "Pass with Conditions" because unresolved unknowns exist, your conditions[] should generally include one addressing each unknown listed, phrased as a concrete way to resolve it.

Output ONLY one JSON object with these keys:
- "outcome": one of "Reject", "Hold", "Reformulate", "Pass with Conditions", "Advance" -- must be equal to or more conservative than "ceiling".
- "narrative": a non-empty string explaining your reasoning, grounded in the specific claims/unknowns/stress_tests given.
- Exactly one payload key, matching your chosen outcome:
  - "Reject": "decisive_evidence" -- a non-empty array of hypothesis_id or test_id strings from the input.
  - "Hold": "reevaluation_conditions" -- a non-empty string describing what would wake this idea back up.
  - "Reformulate": "reformulation_targets" -- a non-empty array of {"field": hypothesis_id string from the input, "guidance": non-empty string}.
  - "Pass with Conditions": "conditions" -- a non-empty array of {"hypothesis_id": a hypothesis_id from "claims" or "unknowns" ONLY -- never a stress_tests test_id, "condition": non-empty string, phrased to be testable as a real-world experiment}. If a condition is motivated by a stress test breaking, identify and cite the underlying hypothesis it puts at risk instead of the test itself -- you may still name the test by id inside the free-text "condition" string if it helps explain the reasoning.
  - "Advance": "advance_confirmation" -- true.

No prose, no markdown fencing, no explanation outside the JSON object itself."""

PAYLOAD_KEYS: dict[str, str] = {
    "Reject": "decisive_evidence",
    "Hold": "reevaluation_conditions",
    "Reformulate": "reformulation_targets",
    "Pass with Conditions": "conditions",
    "Advance": "advance_confirmation",
}


def _validate_reject(payload: dict, valid_refs: set[str]) -> bool:
    ev = payload.get("decisive_evidence")
    return isinstance(ev, list) and bool(ev) and all(isinstance(x, str) and x in valid_refs for x in ev)


def _validate_hold(payload: dict) -> bool:
    cond = payload.get("reevaluation_conditions")
    return isinstance(cond, str) and bool(cond.strip())


def _validate_reformulate(payload: dict, valid_refs: set[str]) -> bool:
    targets = payload.get("reformulation_targets")
    return (
        isinstance(targets, list) and bool(targets)
        and all(
            isinstance(t, dict)
            and t.get("field") in valid_refs
            and isinstance(t.get("guidance"), str) and t["guidance"].strip()
            for t in targets
        )
    )


def _validate_pass_with_conditions(payload: dict, hypothesis_refs: set[str]) -> bool:
    conditions = payload.get("conditions")
    return (
        isinstance(conditions, list) and bool(conditions)
        and all(
            isinstance(c, dict)
            and c.get("hypothesis_id") in hypothesis_refs
            and isinstance(c.get("condition"), str) and c["condition"].strip()
            for c in conditions
        )
    )


def _validate_advance(payload: dict) -> bool:
    return payload.get("advance_confirmation") is True


_VALIDATORS: dict[str, Callable] = {
    "Reject": lambda p, refs, hyp_refs: _validate_reject(p, refs),
    "Hold": lambda p, refs, hyp_refs: _validate_hold(p),
    "Reformulate": lambda p, refs, hyp_refs: _validate_reformulate(p, refs),
    "Pass with Conditions": lambda p, refs, hyp_refs: _validate_pass_with_conditions(p, hyp_refs),
    "Advance": lambda p, refs, hyp_refs: _validate_advance(p),
}


def call_anthropic_recommendation(payload: dict) -> str:
    """Real LLM call. Same ANTHROPIC_API_KEY / model-pin pattern as every prior packet."""
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set in environment. This must be set "
            "locally by the founder -- never hardcoded, never committed."
        )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        thinking={"type": "disabled"},
        system=RECOMMENDATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    text_blocks = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    return text_blocks[-1] if text_blocks else ""


def recommend_outcome(
    ceiling_result: dict,
    claims_ranked: list[Hypothesis],
    stress_results: list[StressTestResult],
    unknowns_ranked: list[Hypothesis] | None = None,
    llm_call: Callable[[dict], str] = call_anthropic_recommendation,
) -> dict:
    """
    Returns a TheoreticalDecision dict (unchanged shape -- see original
    docstring). unknowns_ranked defaults to None/empty for backward
    compatibility with every existing call site; when provided, its
    hypotheses become valid grounding references on the same terms as
    claims (this packet's fix -- see p1.2_packet_17 §0).

    ceiling_result is Packet #8's compute_ceiling() output, taken as
    given -- never recomputed or second-guessed here.
    """
    unknowns_ranked = unknowns_ranked or []
    ceiling = ceiling_result["ceiling"]
    valid_refs = (
        {h.source_field for h in claims_ranked}
        | {h.source_field for h in unknowns_ranked}
        | {r.test_id for r in stress_results}
    )
    hypothesis_refs = {h.source_field for h in claims_ranked} | {h.source_field for h in unknowns_ranked}

    llm_payload = {
        "ceiling": ceiling,
        "ceiling_reasons": ceiling_result["triggered_by"],
        "claims": [
            {"hypothesis_id": h.source_field, "statement": h.statement or h.raw_dossier_text, "rank_score": h.rank_score}
            for h in claims_ranked
        ],
        "unknowns": [
            {"hypothesis_id": h.source_field, "statement": h.statement or h.raw_dossier_text}
            for h in unknowns_ranked
        ],
        "stress_tests": [
            {"test_id": r.test_id, "outcome_or_severity": r.outcome or r.severity or r.status, "category": r.category}
            for r in stress_results
        ],
    }

    try:
        raw_response = llm_call(llm_payload)
    except Exception:
        raw_response = ""

    fallback = {
        "outcome": "Reject",
        "status": "FALLBACK_REJECT",
        "narrative": None,
        "payload": {"decisive_evidence": ceiling_result["triggered_by"] or ["no_llm_output_and_no_ceiling_trigger"]},
        "allowed_range": {"floor": "Reject", "ceiling": ceiling},
    }

    try:
        raw_response = strip_json_markdown_fence(raw_response)
        parsed = json.loads(raw_response)
        outcome = parsed.get("outcome") if isinstance(parsed, dict) else None
        narrative = parsed.get("narrative") if isinstance(parsed, dict) else None

        if (
            outcome in OUTCOME_ORDER
            and OUTCOME_ORDER[outcome] <= OUTCOME_ORDER[ceiling]
            and isinstance(narrative, str) and narrative.strip()
        ):
            key = PAYLOAD_KEYS[outcome]
            if key in parsed and _VALIDATORS[outcome](parsed, valid_refs, hypothesis_refs):
                return {
                    "outcome": outcome,
                    "status": "LLM_RECOMMENDED",
                    "narrative": narrative.strip(),
                    "payload": {key: parsed[key]},
                    "allowed_range": {"floor": "Reject", "ceiling": ceiling},
                }
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pass

    return fallback


def verify_decision_acceptance(recommendation: dict, ceiling_result: dict, valid_refs: set[str]) -> dict:
    """
    P1.0.6 point 5's acceptance-test contract, as reusable deterministic
    logic (not just a one-off test assertion) -- proves:
      (a) recommendation's allowed_range.ceiling matches ceiling_result
          exactly [ceiling correctness itself is Packet #8's own job,
          already covered by its tests -- this only checks consistency
          between the two artifacts].
      (b) the chosen outcome's order is <= the ceiling's order.
      (c) every grounding reference in the payload resolves to
          valid_refs (skipped for Hold/Advance, which carry no
          artifact-ID grounding requirement by P1.0.6 point 4's own
          design; skipped for a FALLBACK_REJECT's own triggered_by
          strings, which are system-generated and trusted by
          construction, not LLM output requiring validation).

    Deliberately does NOT judge whether the specific outcome choice
    was the "right" one -- P1.0.6 point 5 says this explicitly:
    genuinely judgment-dependent by design.

    Returns {"valid": bool, "failures": [str, ...]}.
    """
    failures: list[str] = []

    if recommendation["allowed_range"]["ceiling"] != ceiling_result["ceiling"]:
        failures.append("allowed_range.ceiling does not match the computed ceiling")

    outcome = recommendation["outcome"]
    if OUTCOME_ORDER[outcome] > OUTCOME_ORDER[ceiling_result["ceiling"]]:
        failures.append("outcome exceeds the allowed ceiling")

    refs: list[str] = []
    if recommendation["status"] == "LLM_RECOMMENDED":
        payload = recommendation["payload"]
        if outcome == "Reject":
            refs = payload.get("decisive_evidence", [])
        elif outcome == "Reformulate":
            refs = [t["field"] for t in payload.get("reformulation_targets", [])]
        elif outcome == "Pass with Conditions":
            refs = [c["hypothesis_id"] for c in payload.get("conditions", [])]
        # Hold and Advance carry no artifact-ID grounding requirement.

    for ref in refs:
        if ref not in valid_refs:
            failures.append(f"grounding reference '{ref}' does not resolve to a real artifact")

    return {"valid": not failures, "failures": failures}
