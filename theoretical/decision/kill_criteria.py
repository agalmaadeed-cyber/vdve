"""
Kill Criteria Match detection (P1.0.6 point 2).

Text-interpretation task against F2 (kill_criteria) -- explicitly NOT
arithmetic, so it is the one place in the five-outcome decision system
where an LLM call is legitimate (same category as hypothesis phrasing,
P1.0.2, and the qualitative stress-test probe, Packet #6 -- a
genuinely generative/interpretive sub-task, governed by the same
guard-clause discipline as every other one in this codebase).

F2 is read directly from the Dossier -- it is the founder's own
"ruler" field (EXTRACTION_EXCLUSIONS, P1.0.2), never routed through
the hypothesis pipeline, so this is the one place the decision layer
legitimately reads a raw Dossier field rather than an
already-governed artifact -- consistent with P1.0.2's own design,
which excluded F1/F2 from hypothesis extraction specifically because
they are the measuring rulers, not hypotheses to test.

Detection only ever SURFACES a possible match -- it never activates
the Reject ceiling by itself (P1.0.6 point 2: "founder confirmation
is what activates the hard Reject ceiling, not the system's own
detection"). Founder confirmation is a separate boolean, collected
by a future UI packet, fed into ceiling.compute_ceiling() alongside
this function's output.
"""

from __future__ import annotations

import json
import os
from typing import Callable

from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.stress_tests.engine import StressTestResult

KILL_CHECK_SYSTEM_PROMPT = """You check whether a venture's current evidence shows a possible match against its own founder-declared kill criteria.

You will receive one JSON object: {"kill_criteria_text": str, "stress_test_summaries": [{"test_id": str, "outcome": str, "category": str}], "top_hypotheses": [{"field_code": str, "statement": str}]}.

Output ONLY one JSON object with exactly three keys:
- "possible_match": true or false.
- "rationale": a non-empty string, grounded specifically in kill_criteria_text and at least one specific item from stress_test_summaries or top_hypotheses -- never a generic statement.
- "grounding_refs": an array of the specific test_id or field_code strings your rationale actually references. Must be non-empty if possible_match is true.

No prose, no markdown fencing, no explanation outside the JSON object itself."""


def get_kill_criteria_text(dossier: dict) -> str:
    """
    Walks dossier["sections"] (this codebase's own idiom -- see
    theoretical/hypothesis_extraction/scanner.py) looking for the
    field object whose field_code == "F2". Returns its "value", or
    an empty string if F2 is genuinely absent from this Dossier
    (never a crash -- an idea with no declared kill criteria simply
    can never trigger this check, which is the correct behavior, not
    an error).
    """
    for section_fields in dossier.get("sections", {}).values():
        for field_obj in section_fields.values():
            if field_obj.get("field_code") == "F2":
                return field_obj.get("value", "") or ""
    return ""


def call_anthropic_kill_check(payload: dict) -> str:
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
        max_tokens=1024,
        system=KILL_CHECK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    return message.content[0].text


def detect_kill_criteria_match(
    dossier: dict,
    stress_results: list[StressTestResult],
    claims_ranked: list[Hypothesis],
    llm_call: Callable[[dict], str] = call_anthropic_kill_check,
) -> dict:
    """
    Returns {"status": "COMPLETED"|"FAILED", "possible_match": bool,
    "rationale": str|None, "grounding_refs": [str, ...]}.

    Deterministic shortcut: an empty/missing F2 means there is nothing
    to match against -- returns possible_match=False without any LLM
    call, status="COMPLETED" (there was genuinely nothing to check,
    not a failure to check it).

    Guard-clause governance (same doctrine as every prior packet):
    malformed JSON, a non-bool possible_match, an empty rationale, or
    a possible_match=True with no (or invalid) grounding_refs all
    degrade to status="FAILED". Per this packet's §0, a FAILED
    detection reports possible_match=True -- fail-cautious, not
    fail-silent (see §0 for the full rationale).
    """
    kill_text = get_kill_criteria_text(dossier)
    if not kill_text.strip():
        return {"status": "COMPLETED", "possible_match": False, "rationale": None, "grounding_refs": []}

    valid_refs = {r.test_id for r in stress_results} | {h.source_field for h in claims_ranked}
    payload = {
        "kill_criteria_text": kill_text,
        "stress_test_summaries": [
            {"test_id": r.test_id, "outcome": r.outcome or r.severity or r.status, "category": r.category}
            for r in stress_results
        ],
        "top_hypotheses": [
            {"field_code": h.source_field, "statement": h.statement or h.raw_dossier_text}
            for h in claims_ranked[:5]
        ],
    }

    try:
        raw_response = llm_call(payload)
    except Exception:
        raw_response = ""

    try:
        parsed = json.loads(raw_response)
        possible_match = parsed.get("possible_match")
        rationale = parsed.get("rationale")
        grounding_refs = parsed.get("grounding_refs")

        valid = (
            isinstance(parsed, dict)
            and isinstance(possible_match, bool)
            and isinstance(rationale, str) and rationale.strip()
            and isinstance(grounding_refs, list)
            and all(isinstance(g, str) for g in grounding_refs)
            and (not possible_match or (grounding_refs and all(g in valid_refs for g in grounding_refs)))
        )
        if valid:
            return {
                "status": "COMPLETED",
                "possible_match": possible_match,
                "rationale": rationale.strip(),
                "grounding_refs": grounding_refs,
            }
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pass

    # Fail-cautious per §0: a detection failure reports possible_match=True,
    # capping the ceiling at Hold -- never silently "no match".
    return {"status": "FAILED", "possible_match": True, "rationale": None, "grounding_refs": []}
