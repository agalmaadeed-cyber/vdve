"""
VDVE -- Theoretical Validation Cycle, minimal UI (P1.1/P1.2, LLM
activation added in Packet #14).

No persistent storage backend -- st.session_state only (see Packet
#13's own header for the working-Dossier session-state pattern).

Six LLM-optional features can each be switched between their real
Anthropic-backed implementation and a deterministic no-op stub via
sidebar checkboxes, all default OFF: (a) hypothesis phrasing,
(b) risk adjustment, (c) parameter extraction, (d) qualitative stress
probes, (e) evidence agent, (f) outcome recommendation. Flags render
only when ANTHROPIC_API_KEY resolves (from .streamlit/secrets.toml or
the environment) -- with no key, the app runs exactly as before, with
a one-line banner, no crash (Packet #14 §0(b)/(c)).

Kill-criteria detection is deliberately NOT one of the six flags --
Packet #10 §0's fail-cautious cascade reasoning holds regardless of
key availability; it stays founder-manual review.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from theoretical.llm_utils import escape_markdown_dollar
from theoretical.hypothesis_extraction.scanner import scan_dossier
from theoretical.hypothesis_extraction.phrasing import phrase_hypotheses, call_anthropic_phrasing
from theoretical.hypothesis_extraction.ranking import rank_hypotheses, call_anthropic_risk_adjustment
from theoretical.evidence_gathering.agent import gather_evidence, call_anthropic_evidence_search
from theoretical.evidence_gathering.review import build_evidence_update_trigger
from theoretical.dossier_versioning.version import build_new_version
from theoretical.simulation.parameter_extraction import (
    apply_founder_overrides,
    extract_parameters,
    call_anthropic_parameter_extraction,
)
from theoretical.simulation.unit_economics import (
    INDEPENDENTS,
    compute_metric_evidence_labels,
    compute_scenarios,
)
from theoretical.stress_tests.engine import (
    generate_test_specs,
    run_all_fixed_tests,
    run_qualitative_probe,
    call_anthropic_probe,
)
from theoretical.decision.ceiling import compute_ceiling
from theoretical.decision.kill_criteria import get_kill_criteria_text
from theoretical.decision.outcome import recommend_outcome, verify_decision_acceptance, call_anthropic_recommendation

EVIDENCE_ICONS = {
    "CONFIRMED": "✅",       # same five icons as Idea Dossier
    "ESTIMATE": "\U0001F4CA",
    "FOUNDER_OPINION": "\U0001F5E3️",
    "ASSUMPTION": "⚠️",
    "UNKNOWN": "❓",
}

OUTCOME_ICONS = {
    "SURVIVES": "✅",
    "DEGRADED": "⚠️",
    "BREAKS": "\U0001F534",
    "NOT_EVALUABLE": "❓",
}

EVIDENCE_SEARCH_ICONS = {
    "FOUND": "\U0001F50E",
    "NO_EVIDENCE_FOUND": "❓",
    "NOT_SEARCHED": "⏳",
}

DECISION_ICONS = {
    "Reject": "\U0001F534",
    "Hold": "⏸️",
    "Reformulate": "\U0001F504",
    "Pass with Conditions": "⚠️",
    "Advance": "✅",
}


def _no_llm_probe_call(spec: dict) -> str:
    return ""


def _no_llm_recommendation_call(payload: dict) -> str:
    return ""


def _no_llm_evidence_call(hypotheses: list) -> str:
    return ""


def _load_anthropic_key() -> str | None:
    """
    Streamlit secrets.toml is the source of truth (matches the
    already-deployed pattern in Unicorn Hunter / Idea Dossier) --
    never hardcoded, never committed. Falls back to an already-set
    environment variable. Absence is a declared, graceful state --
    wrapped in try/except since st.secrets' exact behavior with no
    secrets file present varies across Streamlit versions; it must
    never raise here, only resolve to None (Packet #14 §0(b)).
    """
    key = None
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        key = None
    if not key:
        key = os.environ.get("ANTHROPIC_API_KEY")
    return key or None


# Registered acceptance numbers -- phase1_decisions_log.md (P1.0.2 / P1.0.3).
# Only valid at working_dossier version 1 -- see Packet #13's §0(b).
KNOWN_ACCEPTANCE = {
    "DS-0FE02838.json": {"total": 13, "claim": 13, "unknown": 0},
    "DS-SYNTH-PARTIAL.json": {"total": 13, "claim": 8, "unknown": 5},
}

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

st.set_page_config(page_title="VDVE - Theoretical Validation Cycle", layout="wide")
st.title("VDVE - Theoretical Validation Cycle (P1.1/P1.2)")

# --- LLM key + feature flags (Packet #14) ---
_anthropic_key = _load_anthropic_key()
if _anthropic_key:
    os.environ["ANTHROPIC_API_KEY"] = _anthropic_key  # every call_anthropic_* function reads this directly

st.sidebar.header("LLM Features")
if _anthropic_key:
    st.sidebar.success("ANTHROPIC_API_KEY detected.")
    flag_phrasing = st.sidebar.checkbox("a. Hypothesis phrasing", value=False, key="flag_phrasing")
    flag_risk_adj = st.sidebar.checkbox("b. Risk adjustment (±1)", value=False, key="flag_risk_adj")
    flag_param_extraction = st.sidebar.checkbox("c. Parameter extraction", value=False, key="flag_param_extraction")
    flag_probes = st.sidebar.checkbox("d. Qualitative stress probes", value=False, key="flag_probes")
    flag_evidence = st.sidebar.checkbox("e. Evidence agent (web search)", value=False, key="flag_evidence")
    flag_recommendation = st.sidebar.checkbox("f. Outcome recommendation", value=False, key="flag_recommendation")
else:
    st.info("\U0001F50C LLM features: OFF -- deterministic baseline (no ANTHROPIC_API_KEY found in secrets.toml or environment).")
    flag_phrasing = flag_risk_adj = flag_param_extraction = flag_probes = flag_evidence = flag_recommendation = False

# --- Dossier selection ---
st.sidebar.header("Dossier Input")
source = st.sidebar.radio("Source", ["Fixture", "Upload"])

dossier = None
dossier_filename = None

if source == "Fixture":
    fixture_name = st.sidebar.selectbox("Fixture", list(KNOWN_ACCEPTANCE.keys()))
    with open(FIXTURES_DIR / fixture_name, encoding="utf-8") as f:
        dossier = json.load(f)
    dossier_filename = fixture_name
else:
    uploaded = st.sidebar.file_uploader("Upload Dossier JSON", type="json")
    if uploaded:
        dossier = json.load(uploaded)
        dossier_filename = uploaded.name

if dossier is None:
    st.info("Select a fixture or upload a Dossier JSON to begin.")
    st.stop()

# --- Working Dossier: session-scoped, mutable across evidence approvals ---
if (
    "working_dossier" not in st.session_state
    or st.session_state.get("working_dossier_id") != dossier.get("dossier_id")
):
    st.session_state["working_dossier"] = copy.deepcopy(dossier)
    st.session_state["working_dossier_id"] = dossier.get("dossier_id")
    st.session_state.pop("approved_params", None)

working_dossier = st.session_state["working_dossier"]

st.header(f"Dossier: {working_dossier.get('dossier_id', 'unknown')}")
st.metric("Working Dossier Version", f"v{working_dossier.get('version', 1)}")
st.caption(
    "This version advances only when you approve at least one Evidence "
    "Review proposal below (Section 3) -- never persisted beyond this "
    "browser session."
)

# --- Step 1: Scanner ---
scan_result = scan_dossier(working_dossier)

hypotheses_for_pipeline = scan_result.hypotheses
if flag_phrasing:
    hypotheses_for_pipeline = phrase_hypotheses(scan_result.hypotheses, llm_call=call_anthropic_phrasing)

# --- Live acceptance bar: the page itself is an acceptance test ---
if working_dossier.get("version", 1) == 1 and dossier_filename in KNOWN_ACCEPTANCE:
    expected = KNOWN_ACCEPTANCE[dossier_filename]
    actual = {
        "total": scan_result.total,
        "claim": scan_result.claim_count,
        "unknown": scan_result.unknown_count,
    }
    msg = (
        f"Expected {expected['total']}/{expected['claim']}/{expected['unknown']} "
        f"(total/claim/unknown) -- actual {actual['total']}/{actual['claim']}/{actual['unknown']}"
    )
    if actual == expected:
        st.success(f"✅ Acceptance check: {msg} -- MATCH")
    else:
        st.error(f"❌ Acceptance check: {msg} -- MISMATCH")
elif working_dossier.get("version", 1) > 1:
    st.info(
        f"Working Dossier is at v{working_dossier['version']} (evolved via approved "
        f"evidence) -- v1 acceptance numbers no longer apply by design. Actual: "
        f"{scan_result.total}/{scan_result.claim_count}/{scan_result.unknown_count}"
    )
else:
    st.info(
        f"No registered acceptance numbers for this file. "
        f"Actual: {scan_result.total}/{scan_result.claim_count}/{scan_result.unknown_count}"
    )

# --- Step 2: Hypothesis table ---
st.subheader("1. Hypothesis Extraction")
hyp_rows = [
    {
        "field_code": h.source_field,
        "section": h.source_section,
        "type": h.hypothesis_type,
        "evidence": f"{EVIDENCE_ICONS.get(h.original_evidence_label, '')} {h.original_evidence_label}",
        "raw_text": (h.raw_dossier_text[:80] + "...") if len(h.raw_dossier_text) > 80 else h.raw_dossier_text,
        "statement": h.statement if h.statement else "(not phrased)",
        "phrasing_status": h.phrasing_status,
    }
    for h in hypotheses_for_pipeline
]
st.dataframe(hyp_rows, use_container_width=True)
st.caption(f"Excluded fields (EXTRACTION_EXCLUSIONS): {scan_result.excluded_fields}")

# --- Step 3: Ranking ---
st.subheader("2. Ranking (risk x uncertainty)")
claims_ranked, unknowns_ranked = rank_hypotheses(
    hypotheses_for_pipeline,
    llm_call=call_anthropic_risk_adjustment if flag_risk_adj else None,
)

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Claims** (ranked by `rank_score`, feed simulation/stress tests)")
    st.dataframe(
        [
            {
                "rank": h.rank, "field": h.source_field,
                "risk": h.risk_score, "uncertainty": h.uncertainty_score,
                "rank_score": h.rank_score, "adjustment_status": h.adjustment_status,
            }
            for h in claims_ranked
        ],
        use_container_width=True,
    )
with col2:
    st.markdown("**Unknowns** (ranked by `risk_score`, feed evidence-gathering priority)")
    st.dataframe(
        [
            {
                "rank": h.rank, "field": h.source_field,
                "risk": h.risk_score, "uncertainty": h.uncertainty_score,
                "rank_score": h.rank_score, "adjustment_status": h.adjustment_status,
            }
            for h in unknowns_ranked
        ],
        use_container_width=True,
    )

# --- Step 4: Evidence Search / Evidence Review ---
st.subheader("3. Evidence Search / Evidence Review")

all_hyps_for_search = claims_ranked + unknowns_ranked
current_hyp_ids = {h.source_field for h in all_hyps_for_search}

use_mock = st.checkbox(
    "Load mock evidence proposals (demo -- zero cost, no API key)",
    value=not flag_evidence,
    key=f"use_mock_{working_dossier['dossier_id']}",
)

if use_mock:
    with open(FIXTURES_DIR / "mock_evidence_proposals.json", encoding="utf-8") as f:
        mock_proposals = json.load(f)
    proposals = [p for p in mock_proposals if p["hypothesis_id"] in current_hyp_ids]
    st.caption(
        "Showing hand-authored mock proposals -- proves the full "
        "approve -> vN+1 -> re-extraction loop with zero cost and no API key."
    )
elif flag_evidence:
    evidence_results = gather_evidence(
        all_hyps_for_search, working_dossier.get("version", 1), llm_call=call_anthropic_evidence_search
    )
    proposals = [asdict(r) for r in evidence_results]
    st.caption("Live evidence search active (real web search) -- proposals below are genuine.")
else:
    evidence_results = gather_evidence(
        all_hyps_for_search, working_dossier.get("version", 1), llm_call=_no_llm_evidence_call
    )
    proposals = [asdict(r) for r in evidence_results]
    st.caption(
        "Deterministic baseline mode (no LLM active for this screen) -- "
        "every proposal below shows search_status=NOT_SEARCHED."
    )

approved_ids = set()
if not proposals:
    st.info("No evidence proposals for the current hypothesis pool.")
for p in proposals:
    icon = EVIDENCE_SEARCH_ICONS.get(p["search_status"], "")
    with st.expander(f"{icon} {p['hypothesis_id']} -- {p['search_status']}"):
        if p["search_status"] == "FOUND":
            st.write(f"**Proposed value:** {escape_markdown_dollar(p['proposed_value'])}")
            st.write(f"**Proposed evidence_label:** {p['proposed_evidence_label']}")
            st.write(f"**Source:** {escape_markdown_dollar(p['source'])}")
            st.write(f"**Grounding excerpt:** {escape_markdown_dollar(p['citation_excerpt'])}")
            approve = st.checkbox(
                "Approve this proposal",
                key=f"approve_{p['hypothesis_id']}_{working_dossier['version']}",
            )
            if approve:
                approved_ids.add(p["hypothesis_id"])
        else:
            st.caption("Nothing to approve for this status -- no proposed value exists.")

if st.button("Apply Approved Evidence"):
    trigger = build_evidence_update_trigger(proposals, approved_ids)
    if trigger["updates"]:
        result = build_new_version(working_dossier, trigger)
        st.session_state["working_dossier"] = result["dossier"]
        st.session_state.pop("approved_params", None)
        st.success(
            f"Applied {len(trigger['updates'])} approved proposal(s). "
            f"New version: v{result['dossier']['version']}."
        )
        st.rerun()
    else:
        st.info("No proposals were approved -- nothing to apply, no new version written.")

# --- Step 5: Parameter Extraction + Review ---
st.subheader("4. Parameter Extraction + Review")
extracted = extract_parameters(
    working_dossier,
    llm_call=call_anthropic_parameter_extraction if flag_param_extraction else None,
)
st.caption(
    "Live extraction active." if flag_param_extraction else
    "Deterministic baseline mode -- every parameter below is MISSING until you fill it in and approve."
)

overrides = {}
param_cols = st.columns(len(INDEPENDENTS))
for i, param in enumerate(INDEPENDENTS):
    info = extracted[param]
    icon = EVIDENCE_ICONS.get(info["evidence_label"], "")
    with param_cols[i]:
        st.markdown(f"**{param}**")
        st.caption(f"{icon} {info['evidence_label']} | {info['extraction_status']}")
        st.caption(f"source: {info['source_fields'] or 'none'}")
        default_value = info["value"] if info["value"] is not None else 0.0
        val = st.number_input(
            f"value_{param}", value=float(default_value),
            key=f"param_{param}_{dossier_filename}_v{working_dossier['version']}_{flag_param_extraction}",
            label_visibility="collapsed",
        )
        overrides[param] = {"value": val, "evidence_label": "FOUNDER_OPINION"}

if st.button("Approve Parameters"):
    st.session_state["approved_params"] = apply_founder_overrides(extracted, overrides)
    st.success("Parameters approved.")

approved = st.session_state.get("approved_params")

# --- Step 6: Simulation ---
scenarios = None
if approved:
    st.subheader("5. Simulation Scenarios")

    param_labels = {p: approved[p]["evidence_label"] for p in INDEPENDENTS}
    metric_labels = compute_metric_evidence_labels(param_labels)

    scenario_input = {
        p: {"value": approved[p]["value"], "evidence_label": approved[p]["evidence_label"]}
        for p in INDEPENDENTS
    }
    scenarios = compute_scenarios(scenario_input)

    for scenario_name in ("base", "conservative", "optimistic"):
        st.markdown(f"**{scenario_name.capitalize()}**")
        row = scenarios[scenario_name]
        display_row = {}
        for field, value in row.items():
            icon = EVIDENCE_ICONS.get(metric_labels.get(field, "UNKNOWN"), "")
            display_row[field] = f"{icon} {value if value is not None else 'MISSING'}"
        st.dataframe([display_row], use_container_width=True)
else:
    st.info("Approve parameters above to run simulation.")

# --- Step 7: Stress Tests ---
fixed_results = None
generated_results = None
if approved:
    st.subheader("6. Stress Tests")

    scenario_input_for_shocks = {
        p: {"value": approved[p]["value"], "evidence_label": approved[p]["evidence_label"]}
        for p in INDEPENDENTS
    }

    st.markdown("**Fixed library** (6 tests, deterministic, no LLM)")
    fixed_results = run_all_fixed_tests(scenario_input_for_shocks)
    st.dataframe(
        [
            {
                "test_id": r.test_id, "category": r.category,
                "shocked_param": r.shocked_param, "multiplier": r.shock_multiplier,
                "affected_metric": r.affected_metric, "value": r.metric_value,
                "outcome": f"{OUTCOME_ICONS.get(r.outcome, '')} {r.outcome}",
            }
            for r in fixed_results
        ],
        use_container_width=True,
    )

    st.markdown("**Generated tests** (top-3 ranked claims, qualitative probes)")
    st.caption("Live probes active." if flag_probes else "Deterministic baseline mode -- every generated test below shows status=FAILED.")
    generated_specs = generate_test_specs(claims_ranked, n=3)
    generated_results = [
        run_qualitative_probe(spec, llm_call=call_anthropic_probe if flag_probes else _no_llm_probe_call)
        for spec in generated_specs
    ]
    st.dataframe(
        [
            {
                "test_id": r.test_id, "category": r.category,
                "target_hypothesis_id": r.target_hypothesis_id,
                "overlaps_with_fixed": ", ".join(r.overlaps_with_fixed) or "none",
                "status": r.status, "severity": r.severity or "-",
            }
            for r in generated_results
        ],
        use_container_width=True,
    )
else:
    st.info("Approve parameters above to run stress tests.")

# --- Step 8: Theoretical Decision ---
ceiling_result = None
recommendation = None
acceptance = None
if approved:
    st.subheader("7. Theoretical Decision")

    all_stress_results = (fixed_results or []) + (generated_results or [])

    st.markdown("**Kill Criteria Check**")
    kill_text = get_kill_criteria_text(working_dossier)
    if kill_text.strip():
        st.text_area("F2 -- kill_criteria (read-only)", value=kill_text, height=100, disabled=True)
        st.caption("Automated detection intentionally not wired -- see Packet #14 header. Read the text above yourself and classify it.")
        kill_status = st.radio(
            "Founder review",
            ["No concern", "Possible match (unconfirmed)", "Confirmed match"],
            key=f"kill_status_{dossier_filename}_v{working_dossier['version']}",
        )
        kill_match_detected = kill_status != "No concern"
        kill_match_confirmed = kill_status == "Confirmed match"
    else:
        st.caption("No kill_criteria (F2) declared for this Dossier.")
        kill_match_detected = False
        kill_match_confirmed = False

    ceiling_result = compute_ceiling(
        unknowns_ranked, all_stress_results, kill_match_confirmed, kill_match_detected
    )
    st.markdown(f"**Ceiling: {DECISION_ICONS.get(ceiling_result['ceiling'], '')} {ceiling_result['ceiling']}**")
    if ceiling_result["triggered_by"]:
        st.caption("Triggered by: " + "; ".join(ceiling_result["triggered_by"]))
    else:
        st.caption("No ceiling triggers -- nothing capped this idea below Advance.")

    st.markdown("**Recommendation**")
    st.caption("Live recommendation active." if flag_recommendation else "Deterministic baseline mode -- always falls back to Reject (status=FALLBACK_REJECT).")
    recommendation = recommend_outcome(
        ceiling_result, claims_ranked, all_stress_results, unknowns_ranked,
        llm_call=call_anthropic_recommendation if flag_recommendation else _no_llm_recommendation_call,
    )
    st.write(f"{DECISION_ICONS.get(recommendation['outcome'], '')} **{recommendation['outcome']}** ({recommendation['status']})")
    st.json(recommendation["payload"])

    valid_refs = (
        {h.source_field for h in claims_ranked}
        | {h.source_field for h in unknowns_ranked}
        | {r.test_id for r in all_stress_results}
    )
    acceptance = verify_decision_acceptance(recommendation, ceiling_result, valid_refs)
    if acceptance["valid"]:
        st.success("✅ Decision acceptance check: valid (ceiling matches, range respected, grounding resolved).")
    else:
        st.error("❌ Decision acceptance check failed: " + "; ".join(acceptance["failures"]))
else:
    st.info("Approve parameters above to compute a theoretical decision.")

# --- Step 9: Export ---
if scenarios:
    st.subheader("8. Export")
    export_data = {
        "dossier_id": working_dossier.get("dossier_id"),
        "dossier_version": working_dossier.get("version"),
        "hypotheses": {
            "claims": [asdict(h) for h in claims_ranked],
            "unknowns": [asdict(h) for h in unknowns_ranked],
        },
        "approved_parameters": approved,
        "scenarios": scenarios,
        "stress_tests": {
            "fixed": [asdict(r) for r in fixed_results] if fixed_results else [],
            "generated": [asdict(r) for r in generated_results] if generated_results else [],
        },
        "theoretical_decision": {
            "ceiling": ceiling_result,
            "recommendation": recommendation,
            "acceptance": acceptance,
        } if ceiling_result else {},
    }
    st.download_button(
        "Export JSON",
        data=json.dumps(export_data, indent=2, default=str, ensure_ascii=False),
        file_name=f"vdve_export_{working_dossier.get('dossier_id', 'unknown')}_v{working_dossier.get('version')}.json",
        mime="application/json",
    )
    st.caption("This export is the seed of the P1.2 Stress Test input contract -- the first full run's artifact, saved.")
