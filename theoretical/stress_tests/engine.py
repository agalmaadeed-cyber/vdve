"""
Stress-test execution engine (P1.0.5).

Two independent paths, per the type split P1.0.5 mandates:
- run_quantitative_shock(): pure deterministic re-run of
  theoretical.simulation.unit_economics.compute_unit_economics() with
  exactly one INDEPENDENT shocked. No LLM anywhere in this path --
  same doctrine as Packet #4's simulation.
- run_qualitative_probe(): a single, narrowly-scoped LLM call per
  hypothesis, constrained to a structured severity classification,
  governed by the same guard-clause doctrine as Packets #2/#3
  (identity check, non-empty grounded rationale, graceful degradation
  to status="FAILED" on any parse or grounding failure -- never an
  invented severity).

generate_test_specs() derives the generated-test set from the ranked
"claim" hypothesis list (P1.0.3), never "unknown"-type hypotheses
(P1.0.2's routing split -- there is nothing to stress-test in an
unresolved unknown).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.llm_utils import strip_json_markdown_fence
from theoretical.simulation.unit_economics import INDEPENDENTS, compute_unit_economics
from theoretical.stress_tests.fixed_library import FIXED_TESTS, SECTION_TO_CATEGORY

QUANTITATIVE_SHOCK = "quantitative_shock"
QUALITATIVE_PROBE = "qualitative_probe"

PROBE_SYSTEM_PROMPT = """You assess a single business hypothesis for a qualitative risk (regulation, trust, competitive response, or similar -- never a numeric/financial claim, those are handled elsewhere).

You will receive one JSON object: {"hypothesis_id": str, "category": str, "statement": str, "raw_text": str}.

Output ONLY one JSON object with exactly three keys:
- "hypothesis_id": copied exactly from the input, unchanged.
- "severity": one of "LOW", "MEDIUM", "CRITICAL".
- "rationale": a non-empty string grounded specifically in the given statement/raw_text -- reference the actual content, never a generic template answer.

No prose, no markdown fencing, no explanation outside the JSON object itself."""


@dataclass
class StressTestResult:
    test_id: str
    test_type: str  # "quantitative_shock" | "qualitative_probe"
    category: str
    source: str  # "fixed_library" | "generated"
    status: str  # "COMPLETED" | "FAILED"
    target_hypothesis_id: str | None = None  # generated tests only
    overlaps_with_fixed: list[str] = field(default_factory=list)  # generated tests only

    # quantitative_shock fields (None for probes)
    shocked_param: str | None = None
    shock_multiplier: float | None = None
    affected_metric: str | None = None
    break_threshold: float | None = None
    degraded_ceiling: float | None = None
    metric_value: float | None = None
    outcome: str | None = None  # "SURVIVES" | "DEGRADED" | "BREAKS" | "NOT_EVALUABLE"

    # qualitative_probe fields (None for shocks)
    severity: str | None = None
    rationale: str | None = None


def _apply_shock(
    approved_params: dict[str, dict], shocked_param: str, multiplier: float
) -> dict[str, float | None]:
    """
    approved_params: {independent_name: {"value": float|None, ...}} for
    each of the six INDEPENDENTS (Packet #4's approved-parameter shape).
    Returns a plain {name: value} dict with exactly one field shocked;
    every other field passes through at its approved base value
    unchanged. A None base value stays None -- multiplying None is
    never attempted (P1.0.4b.4's "never a silent default" rule extends
    here: a missing input stays missing, it does not become 0 or any
    other invented number).
    """
    values: dict[str, float | None] = {}
    for name in INDEPENDENTS:
        entry = approved_params.get(name, {"value": None})
        values[name] = entry.get("value")

    base = values.get(shocked_param)
    values[shocked_param] = (base * multiplier) if base is not None else None
    return values


def run_quantitative_shock(
    test_spec: dict, approved_params: dict[str, dict]
) -> StressTestResult:
    """
    Executes one fixed_library-shaped test_spec dict against a
    founder-approved parameter set. Deterministic, no LLM. Design
    decisions closing the NOT_EVALUABLE and DEGRADED gaps: see this
    packet's §0.
    """
    shocked_values = _apply_shock(
        approved_params, test_spec["shocked_param"], test_spec["shock_multiplier"]
    )
    result = compute_unit_economics(shocked_values)
    metric_value = result.get(test_spec["affected_metric"])

    if metric_value is None:
        outcome = "NOT_EVALUABLE"
    elif metric_value < test_spec["break_threshold"]:
        outcome = "BREAKS"
    elif metric_value < test_spec["degraded_ceiling"]:
        outcome = "DEGRADED"
    else:
        outcome = "SURVIVES"

    return StressTestResult(
        test_id=test_spec["test_id"],
        test_type=QUANTITATIVE_SHOCK,
        category=test_spec["category"],
        source="fixed_library",
        status="COMPLETED",
        shocked_param=test_spec["shocked_param"],
        shock_multiplier=test_spec["shock_multiplier"],
        affected_metric=test_spec["affected_metric"],
        break_threshold=test_spec["break_threshold"],
        degraded_ceiling=test_spec["degraded_ceiling"],
        metric_value=metric_value,
        outcome=outcome,
    )


def run_all_fixed_tests(approved_params: dict[str, dict]) -> list[StressTestResult]:
    return [run_quantitative_shock(spec, approved_params) for spec in FIXED_TESTS]


def generate_test_specs(claims_ranked: list[Hypothesis], n: int = 3) -> list[dict]:
    """
    Derives up to n generated qualitative_probe specs from the top-N
    ranked "claim" hypotheses (P1.0.3's own ordering, no re-ranking
    here). n=3 is a placeholder, same calibrate-later status as every
    other constant introduced this session (P1.0.3b, P1.0.4c, this
    packet's own break_threshold/degraded_ceiling values).

    Every spec declares target_hypothesis_id = the hypothesis's
    source_field -- this codebase's identity key throughout (P1.0.2,
    P1.0.3 both use source_field as the sole identity check; there is
    no separate hypothesis_id field anywhere in the Hypothesis schema).
    overlaps_with_fixed is populated, never hidden (P1.0.5's own
    overlap-transparency rule), by a same-category match against
    FIXED_TESTS -- recorded as a visible link, not a dedup/skip.
    """
    top = claims_ranked[:n]
    specs: list[dict] = []
    for h in top:
        category = SECTION_TO_CATEGORY.get(h.source_field[0], "regulation")
        overlaps = [t["test_id"] for t in FIXED_TESTS if t["category"] == category]
        specs.append(
            {
                "test_id": f"GEN-{h.source_field}",
                "category": category,
                "target_hypothesis_id": h.source_field,
                "statement": h.statement or h.raw_dossier_text,
                "raw_text": h.raw_dossier_text,
                "overlaps_with_fixed": overlaps,
            }
        )
    return specs


def call_anthropic_probe(spec: dict) -> str:
    """
    Real LLM call for one qualitative_probe spec. Reads
    ANTHROPIC_API_KEY from the environment via the SDK's default
    client behavior -- never reads, logs, or touches the key value
    itself. Same model pin as Packet #2's phrasing layer.
    """
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set in environment. This must be set "
            "locally by the founder -- never hardcoded, never committed."
        )

    client = anthropic.Anthropic()
    payload = {
        "hypothesis_id": spec["target_hypothesis_id"],
        "category": spec["category"],
        "statement": spec["statement"],
        "raw_text": spec["raw_text"],
    }
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        thinking={"type": "disabled"},
        system=PROBE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    text_blocks = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    return text_blocks[-1] if text_blocks else ""


def run_qualitative_probe(
    spec: dict, llm_call: Callable[[dict], str] = call_anthropic_probe
) -> StressTestResult:
    """
    Executes one generated probe spec. Guard-clause governance
    identical in spirit to Packets #2/#3: identity check against the
    input's own target_hypothesis_id, non-empty grounded rationale
    required, any failure (call exception, malformed JSON, wrong
    severity value, ungrounded/empty rationale) degrades to
    status="FAILED" -- never an invented severity, never a crash.
    """
    try:
        raw_response = llm_call(spec)
    except Exception:
        raw_response = ""

    severity, rationale, ok = None, None, False
    try:
        raw_response = strip_json_markdown_fence(raw_response)
        parsed = json.loads(raw_response)
        if (
            isinstance(parsed, dict)
            and parsed.get("hypothesis_id") == spec["target_hypothesis_id"]
            and parsed.get("severity") in ("LOW", "MEDIUM", "CRITICAL")
            and isinstance(parsed.get("rationale"), str)
            and parsed["rationale"].strip()
        ):
            severity = parsed["severity"]
            rationale = parsed["rationale"].strip()
            ok = True
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return StressTestResult(
        test_id=spec["test_id"],
        test_type=QUALITATIVE_PROBE,
        category=spec["category"],
        source="generated",
        status="COMPLETED" if ok else "FAILED",
        target_hypothesis_id=spec["target_hypothesis_id"],
        overlaps_with_fixed=spec["overlaps_with_fixed"],
        severity=severity,
        rationale=rationale,
    )
