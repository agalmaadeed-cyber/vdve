"""
LLM phrasing layer for the Hypothesis Extraction pipeline.

Implements P1.0.2's phrasing-layer governance:
- The deterministic scanner (Packet #1) already decided WHICH fields
  become hypotheses. This module ONLY converts each selected field into
  a phrased statement — it never adds, removes, or re-selects hypotheses.
- Count guard + identity guard + per-field failure handling are all
  enforced in `apply_phrasing_guards()`, deterministically, regardless
  of what the LLM returns. The LLM's structured output is never trusted
  beyond an exact field_code match against the input.
- A field that fails phrasing is never lost: it keeps
  `statement = raw_dossier_text` and `phrasing_status = "FAILED"`.
- `hypothesis_type` drives phrasing style: "claim" -> a falsifiable
  statement; "unknown" -> an open question naming what must be
  discovered.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Callable

from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.llm_utils import strip_json_markdown_fence

PHRASING_SYSTEM_PROMPT = """You convert Dossier field content into testable hypothesis statements for MVP Studio's Theoretical Validation Cycle.

You will receive a JSON array of items, each with: field_code, hypothesis_type ("claim" or "unknown"), source_section, raw_text (the original Dossier field content, which may be in Arabic or English).

For each item, produce exactly one output object with exactly two keys: "field_code" (copied exactly from the input, unchanged) and "statement" (English text).

Rules:
- If hypothesis_type is "claim": phrase raw_text as a single, falsifiable, testable statement in English -- a claim that could be shown true or false by evidence. Do not add facts not present in raw_text. Do not soften or hedge language beyond what raw_text supports.
- If hypothesis_type is "unknown": phrase raw_text as a single open question in English naming specifically what needs to be discovered. raw_text may be empty; if so, phrase a generic question appropriate to field_code's role.
- Output ONLY a JSON array, one object per input item, in the same order as the input. No prose, no markdown fencing, no explanation outside the JSON array itself.
- Every field_code in your output must be copied exactly from an input item. Never invent a field_code. Never omit an input item."""


def _build_payload(hypotheses: list[Hypothesis]) -> list[dict]:
    return [
        {
            "field_code": h.source_field,
            "hypothesis_type": h.hypothesis_type,
            "source_section": h.source_section,
            "raw_text": h.raw_dossier_text,
        }
        for h in hypotheses
    ]


def call_anthropic_phrasing(hypotheses: list[Hypothesis]) -> str:
    """
    Real LLM call. Reads ANTHROPIC_API_KEY from the environment via the
    Anthropic SDK's default client behavior -- this function never reads,
    logs, or otherwise touches the key value itself.

    Model pinned to "claude-sonnet-5" (current flagship at time of
    writing) -- revisit if MVP Studio's tech-stack decision changes.
    """
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set in environment. This must be set "
            "locally by the founder -- never hardcoded, never committed."
        )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        thinking={"type": "disabled"},
        system=PHRASING_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": json.dumps(_build_payload(hypotheses), ensure_ascii=False),
            }
        ],
    )
    text_blocks = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    return text_blocks[-1] if text_blocks else ""


def apply_phrasing_guards(
    hypotheses: list[Hypothesis], raw_llm_response: str
) -> list[Hypothesis]:
    """
    Deterministic governance layer (P1.0.2). Never mutates the input list.

    - Parses raw_llm_response as JSON. Any parse failure, or a response
      that isn't a JSON array, means EVERY hypothesis falls back to
      phrasing_status="FAILED" with statement=raw_dossier_text.
    - For a valid JSON array, each item is checked individually:
      it counts only if field_code matches an input hypothesis's
      source_field AND statement is a non-empty string. Anything else
      (invented field_code, missing statement, wrong type) is silently
      dropped from consideration -- never persisted, never crashes.
    - Every input hypothesis appears exactly once in the output, in the
      same order, always -- either phrased (from a valid matching item)
      or failed (falling back to its own raw_dossier_text).

    Returns a NEW list; same length and same field_codes as the input,
    unconditionally.
    """
    input_field_codes = {h.source_field for h in hypotheses}

    try:
        raw_llm_response = strip_json_markdown_fence(raw_llm_response)
        parsed = json.loads(raw_llm_response)
        if not isinstance(parsed, list):
            raise ValueError("LLM response is not a JSON array")
    except (json.JSONDecodeError, ValueError):
        parsed = []

    phrasing_by_field: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        field_code = item.get("field_code")
        statement = item.get("statement")
        if (
            isinstance(field_code, str)
            and field_code in input_field_codes
            and field_code not in phrasing_by_field  # first match wins, no overwrite
            and isinstance(statement, str)
            and statement.strip()
        ):
            phrasing_by_field[field_code] = statement.strip()
        # else: invented / malformed / duplicate entry -- dropped, never persisted

    result: list[Hypothesis] = []
    for h in hypotheses:
        if h.source_field in phrasing_by_field:
            result.append(
                replace(
                    h,
                    statement=phrasing_by_field[h.source_field],
                    phrasing_status="PHRASED",
                )
            )
        else:
            result.append(
                replace(
                    h,
                    statement=h.raw_dossier_text,
                    phrasing_status="FAILED",
                )
            )

    return result


def phrase_hypotheses(
    hypotheses: list[Hypothesis],
    llm_call: Callable[[list[Hypothesis]], str] = call_anthropic_phrasing,
) -> list[Hypothesis]:
    """
    Public entry point. `llm_call` is injected for testability -- tests
    pass a stub returning canned JSON strings; production code uses the
    default `call_anthropic_phrasing`, the only place that touches the
    network or the API key.

    A total call failure (network error, auth error, etc.) is treated
    identically to a malformed response -- everything falls back to
    phrasing_status="FAILED", nothing crashes the pipeline.
    """
    try:
        raw_response = llm_call(hypotheses)
    except Exception:
        raw_response = ""  # apply_phrasing_guards() will fail-safe every field

    return apply_phrasing_guards(hypotheses, raw_response)
