"""
Hypothesis ranking module (P1.0.3): risk x uncertainty.

- uncertainty_score: deterministic lookup from original_evidence_label.
  No LLM involvement -- evidence_label is already a carefully maintained
  signal across MVP Studio (P1.0.3a).
- risk_score: a deterministic base weight per Dossier section (P1.0.3b,
  finalized 2026-07-16: A=5, B=5, C=3, D=4, E=3, F=5 -- see
  phases/phase-1/phase1_decisions_log.md for full rationale per
  section, including the corrected reasoning for E), optionally
  adjusted by an LLM within a hard-clamped +/-1 range, requiring a
  non-empty dependent_fields list and rationale -- an adjustment
  missing either is rejected and treated as a failure (P1.0.3b).
- rank_score = risk_score * uncertainty_score, descending.
- Two separate ranked lists, never merged: "claim" hypotheses ranked by
  rank_score; "unknown" hypotheses ranked by risk_score alone in effect
  (their uncertainty_score is fixed at the maximum, 3, for every
  unknown by definition, so it acts as a constant multiplier and does
  not change relative order -- rank_score is still computed and stored
  for schema consistency and auditability).
- Deterministic tie-break: (1) higher risk_score, (2) section order
  A->F, (3) field_code alphabetically -- guarantees a fully reproducible
  total order for identical input, required for stable acceptance tests.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.llm_utils import strip_json_markdown_fence

# a.4 diagnostic session (2026-07-24): the founder observed the same
# hypothesis's adjustment_status non-reproducibly flip between APPLIED
# and FAILED across separate live runs of the same input. The parsing
# logic below is fully deterministic given a fixed raw_llm_response --
# so any flip has to originate either in the raw LLM text itself
# varying between calls, or in validation being stricter than the raw
# response actually warrants. This codebase had NO record anywhere of
# what a raw risk-adjustment response looked like when a flip happened
# -- there was no way to diagnose a past occurrence, only guess. See
# _get_diagnostics_logger() and _log_risk_adjustment_diagnostics() below.
_DIAGNOSTICS_LOGGER_NAME = "vdve.risk_adjustment"
_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "risk_adjustment.log"

UNCERTAINTY_BY_LABEL: dict[str, int] = {
    "ESTIMATE": 1,
    "ASSUMPTION": 2,
    "FOUNDER_OPINION": 2,
    "UNKNOWN": 3,
}

SECTION_WEIGHTS: dict[str, int] = {
    "A": 5,
    "B": 5,
    "C": 3,
    "D": 4,
    "E": 3,
    "F": 5,
}

ADJUSTMENT_CLAMP = 1  # hard bound in code, not just in the prompt (P1.0.3b.1)


def _clamp_adjustment(raw_adjustment: int) -> int:
    return max(-ADJUSTMENT_CLAMP, min(ADJUSTMENT_CLAMP, raw_adjustment))


def _coerce_int_adjustment(adjustment) -> int | None:
    """
    a.4 fix (diagnostic session, 2026-07-24): CONFIRMED root cause of the
    non-reproducible APPLIED/FAILED flip. The system prompt asks the
    model for exactly one of -1, 0, or +1 -- but whether the model
    happens to serialize that as a JSON int (1) or a JSON float (1.0)
    varies between calls (empirically confirmed: json.loads('1.0')
    produces a Python float, and isinstance(1.0, int) is False even
    though it is numerically identical to the int 1). The old strict
    `isinstance(adjustment, int)` check silently rejected the entire
    entry whenever the model's response happened to use the float
    form, even though the proposed adjustment was semantically valid
    -- causing the exact same hypothesis to flip between APPLIED and
    FAILED across otherwise-identical runs purely due to how the model
    chose to format the number that time, not a real change of intent.

    Accepts an int directly, or a float that represents a whole number
    (e.g. 1.0, -1.0, 0.0) and returns it as an int. A float with a
    genuine fractional part (e.g. 0.5) does NOT represent one of the
    three permitted values and is still correctly rejected (returns
    None) -- this fix relaxes the *type* accepted, never the *value*
    space. bool is explicitly rejected even though Python's bool is a
    subclass of int (isinstance(True, int) is True) -- a stray
    True/False must never silently become 1/0; this was a pre-existing,
    separate edge case made visible while writing this coercion check,
    not itself the confirmed root cause, included because it costs
    nothing to guard against here.
    """
    if isinstance(adjustment, bool):
        return None
    if isinstance(adjustment, int):
        return adjustment
    if isinstance(adjustment, float) and adjustment.is_integer():
        return int(adjustment)
    return None


def _get_diagnostics_logger() -> logging.Logger:
    """
    a.4 diagnostic session (2026-07-24): a local, gitignored log file
    (logs/risk_adjustment.log) capturing the raw LLM response and a
    per-hypothesis accept/reject breakdown for every LIVE risk-
    adjustment call (never for the deterministic no-LLM baseline). Pure
    side-channel observability -- never changes apply_risk_adjustment()'s
    parsing logic or its return value. If the log directory can't be
    created or written (e.g. a read-only deployment filesystem), this
    degrades to a no-op logger rather than crashing the ranking
    pipeline -- diagnostics are a bonus, never a dependency of the
    actual feature.
    """
    logger = logging.getLogger(_DIAGNOSTICS_LOGGER_NAME)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                _LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(handler)
        except OSError:
            logger.addHandler(logging.NullHandler())
    return logger


def _log_risk_adjustment_diagnostics(
    raw_llm_response: str,
    input_field_codes: set[str],
    adjustments_by_field: dict[str, dict],
    rejection_reasons: dict[str, str],
) -> None:
    """
    a.4 diagnostic session (2026-07-24): logs one INFO-level entry per
    live risk-adjustment call -- the full raw LLM response text, plus
    every input hypothesis's final determination: APPLIED (with the
    accepted values), REJECTED (with the specific validation check that
    failed), or OMITTED (the model simply proposed no adjustment for
    that field at all -- the expected "no change" case per the system
    prompt, not a failure). This three-way distinction is exactly the
    signal needed to tell a genuine parsing/validation bug apart from
    ordinary LLM judgment variance the next time a flip is observed.
    """
    logger = _get_diagnostics_logger()
    lines = [f"--- risk adjustment call, {len(input_field_codes)} input field(s) ---"]
    for field_code in sorted(input_field_codes):
        if field_code in adjustments_by_field:
            adj = adjustments_by_field[field_code]
            lines.append(
                f"  {field_code}: APPLIED adjustment={adj['adjustment']} "
                f"dependent_fields={adj['dependent_fields']}"
            )
        elif field_code in rejection_reasons:
            lines.append(f"  {field_code}: REJECTED -- {rejection_reasons[field_code]}")
        else:
            lines.append(f"  {field_code}: OMITTED -- model proposed no adjustment for this field")
    lines.append(f"  raw_llm_response: {raw_llm_response!r}")
    logger.info("\n".join(lines))


def compute_uncertainty_score(hypothesis: Hypothesis) -> int:
    return UNCERTAINTY_BY_LABEL[hypothesis.original_evidence_label]


def compute_base_risk_score(hypothesis: Hypothesis) -> int:
    section_letter = hypothesis.source_field[0]
    return SECTION_WEIGHTS[section_letter]


def apply_risk_adjustment(
    hypotheses: list[Hypothesis], raw_llm_response: str
) -> list[Hypothesis]:
    """
    Deterministic governance layer over an optional LLM risk-adjustment
    pass (P1.0.3b). Never mutates the input list.

    Expects raw_llm_response to be a JSON array of objects:
      {"field_code": str, "adjustment": int,
       "dependent_fields": [str, ...], "rationale": str}

    An entry only takes effect if ALL hold:
      - field_code matches an input hypothesis exactly (identity guard),
        and hasn't already been claimed by an earlier entry (first match
        wins, no overwrite -- same rule as the phrasing layer).
      - adjustment is an int, OR a float representing a whole number
        (e.g. 1.0 -- a.4 fix, 2026-07-24: json.loads() can hand back
        either depending on how the model formatted it), clamped to
        [-1, +1] in code regardless of what the LLM proposed.
      - dependent_fields is a non-empty list of field_codes that are
        themselves present among the input hypotheses, excluding the
        hypothesis's own field_code (self-reference is not a
        dependency).
      - rationale is a non-empty string.

    Any failure on any of these -- for that hypothesis only -- falls
    back to the unadjusted base weight, adjustment_status="FAILED". A
    total parse failure (malformed JSON, non-array, or no LLM call at
    all) fails every hypothesis the same way, all falling back to their
    base section weight. Same doctrine as Packet #2's phrasing guards:
    visible, per-item failure, never a silent invention, never a
    pipeline crash.
    """
    input_field_codes = {h.source_field for h in hypotheses}

    try:
        stripped_response = strip_json_markdown_fence(raw_llm_response)
        parsed = json.loads(stripped_response)
        if not isinstance(parsed, list):
            raise ValueError("not an array")
    except (json.JSONDecodeError, ValueError):
        parsed = []

    adjustments_by_field: dict[str, dict] = {}
    rejection_reasons: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        field_code = item.get("field_code")
        adjustment = item.get("adjustment")
        dependent_fields = item.get("dependent_fields")
        rationale = item.get("rationale")

        if field_code not in input_field_codes or field_code in adjustments_by_field:
            continue

        coerced_adjustment = _coerce_int_adjustment(adjustment)
        if coerced_adjustment is None:
            rejection_reasons[field_code] = f"adjustment not a valid int or integral float: {adjustment!r}"
            continue
        if not isinstance(dependent_fields, list) or not dependent_fields:
            rejection_reasons[field_code] = f"dependent_fields missing or empty: {dependent_fields!r}"
            continue
        if not all(
            isinstance(df, str) and df in input_field_codes and df != field_code
            for df in dependent_fields
        ):
            rejection_reasons[field_code] = f"dependent_fields contains an invalid entry: {dependent_fields!r}"
            continue
        if not isinstance(rationale, str) or not rationale.strip():
            rejection_reasons[field_code] = f"rationale missing or empty: {rationale!r}"
            continue

        adjustments_by_field[field_code] = {
            "adjustment": _clamp_adjustment(coerced_adjustment),
            "dependent_fields": dependent_fields,
            "rationale": rationale.strip(),
        }

    if raw_llm_response:
        _log_risk_adjustment_diagnostics(
            raw_llm_response, input_field_codes, adjustments_by_field, rejection_reasons
        )

    result: list[Hypothesis] = []
    for h in hypotheses:
        base = compute_base_risk_score(h)
        if h.source_field in adjustments_by_field:
            adj = adjustments_by_field[h.source_field]
            result.append(
                replace(
                    h,
                    risk_score=base + adj["adjustment"],
                    adjustment_status="APPLIED",
                    dependent_fields=adj["dependent_fields"],
                    adjustment_rationale=adj["rationale"],
                )
            )
        else:
            result.append(
                replace(
                    h,
                    risk_score=base,
                    adjustment_status="FAILED",
                    dependent_fields=[],
                    adjustment_rationale=None,
                )
            )
    return result


def rank_hypotheses(
    hypotheses: list[Hypothesis],
    llm_call: Callable[[list[Hypothesis]], str] | None = None,
) -> tuple[list[Hypothesis], list[Hypothesis]]:
    """
    Full ranking pass (P1.0.3). Returns (claim_ranked, unknown_ranked) --
    two separate lists, never merged, each sorted best-first with `rank`
    populated as the final 1-indexed position.

    If llm_call is None (the default, and this packet's actual tested
    mode), every hypothesis uses its unadjusted base section weight --
    a fully deterministic, zero-cost baseline. Passing a real llm_call
    enables the bounded adjustment pass; failures in it degrade
    gracefully to the same baseline, never crash the ranking.
    """
    with_uncertainty = [
        replace(h, uncertainty_score=compute_uncertainty_score(h)) for h in hypotheses
    ]

    if llm_call is not None:
        try:
            raw_response = llm_call(with_uncertainty)
        except Exception:
            raw_response = ""
    else:
        raw_response = ""

    with_risk = apply_risk_adjustment(with_uncertainty, raw_response)

    with_rank_score = [
        replace(h, rank_score=h.risk_score * h.uncertainty_score) for h in with_risk
    ]

    claims = [h for h in with_rank_score if h.hypothesis_type == "claim"]
    unknowns = [h for h in with_rank_score if h.hypothesis_type == "unknown"]

    def sort_key(h: Hypothesis):
        return (-h.rank_score, -h.risk_score, h.source_field[0], h.source_field)

    claims_sorted = sorted(claims, key=sort_key)
    unknowns_sorted = sorted(unknowns, key=sort_key)

    claims_ranked = [replace(h, rank=i + 1) for i, h in enumerate(claims_sorted)]
    unknowns_ranked = [replace(h, rank=i + 1) for i, h in enumerate(unknowns_sorted)]

    return claims_ranked, unknowns_ranked


RISK_ADJUSTMENT_SYSTEM_PROMPT = """You review a batch of business hypotheses, each already carrying a deterministic base risk weight (1-5) from its Dossier section. Propose a SMALL adjustment (-1, 0, or +1) to any hypothesis whose real-world impact is unusually high or low relative to its section's typical weight, given genuine cross-hypothesis dependencies you can see in this batch.

You will receive a JSON array: [{"field_code": str, "section": str, "statement": str, "base_weight": int}, ...].

For each hypothesis where you have a genuine adjustment to propose, output an object with EXACTLY these keys: "field_code" (copied exactly from input), "adjustment" (-1, 0, or +1), "dependent_fields" (a non-empty array of OTHER field_code strings from the input batch whose validity depends on this hypothesis being true -- never the hypothesis's own field_code), "rationale" (a non-empty string explaining the dependency).

Omit any hypothesis you have no adjustment to propose for -- omission means no change, not zero.

Output ONLY a JSON array of these objects (possibly empty). No prose, no markdown fencing, no explanation outside the JSON array itself."""


def call_anthropic_risk_adjustment(hypotheses: list[Hypothesis]) -> str:
    """
    Real LLM call for the bounded risk-adjustment pass (P1.0.3b).
    Reads ANTHROPIC_API_KEY from the environment via the SDK's default
    client behavior -- never reads, logs, or touches the key value
    itself. Model pinned to "claude-sonnet-5", same as every prior
    packet. hypotheses are expected to already carry uncertainty_score
    (rank_hypotheses() computes this before calling llm_call).
    """
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set in environment. This must be set "
            "locally by the founder -- never hardcoded, never committed."
        )

    payload = [
        {
            "field_code": h.source_field,
            "section": h.source_section,
            "statement": h.statement or h.raw_dossier_text,
            "base_weight": compute_base_risk_score(h),
        }
        for h in hypotheses
    ]
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        thinking={"type": "disabled"},
        system=RISK_ADJUSTMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    text_blocks = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    return text_blocks[-1] if text_blocks else ""
