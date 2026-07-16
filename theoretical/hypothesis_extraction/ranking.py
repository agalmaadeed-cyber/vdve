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
from dataclasses import replace
from typing import Callable

from theoretical.hypothesis_extraction.scanner import Hypothesis

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
      - adjustment is an int, clamped to [-1, +1] in code regardless of
        what the LLM proposed.
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
        parsed = json.loads(raw_llm_response)
        if not isinstance(parsed, list):
            raise ValueError("not an array")
    except (json.JSONDecodeError, ValueError):
        parsed = []

    adjustments_by_field: dict[str, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        field_code = item.get("field_code")
        adjustment = item.get("adjustment")
        dependent_fields = item.get("dependent_fields")
        rationale = item.get("rationale")

        if field_code not in input_field_codes or field_code in adjustments_by_field:
            continue
        if not isinstance(adjustment, int):
            continue
        if not isinstance(dependent_fields, list) or not dependent_fields:
            continue
        if not all(
            isinstance(df, str) and df in input_field_codes and df != field_code
            for df in dependent_fields
        ):
            continue
        if not isinstance(rationale, str) or not rationale.strip():
            continue

        adjustments_by_field[field_code] = {
            "adjustment": _clamp_adjustment(adjustment),
            "dependent_fields": dependent_fields,
            "rationale": rationale.strip(),
        }

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
