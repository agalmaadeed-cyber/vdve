"""
VDVE -- Theoretical Validation Cycle, minimal UI (P1.1, retrofitted
in Packet #13 to the canonical P1.0.9 cycle order).

No persistent storage backend -- st.session_state only. Packet #13
introduces the first within-session-mutable Dossier
(st.session_state["working_dossier"]): approving an Evidence Review
proposal writes a new Dossier version via Packet #11's
build_new_version(), held only in session state -- closing the
browser tab loses it, same as every other piece of state in this app.
Real persistence remains a distinct, later decision.

Canonical cycle order (P1.0.9 point 4), now matched by this page's
own section order:
    Extraction -> Ranking -> Evidence Search/Review ->
    [vN+1 -> re-Extraction] -> Parameter Review -> Simulation ->
    Stress Tests -> Theoretical Decision -> Export

LLM-optional features still running in deterministic baseline mode on
this page (no ANTHROPIC_API_KEY dependency yet): hypothesis phrasing,
ranking adjustment, parameter extraction, qualitative stress probes,
kill-criteria auto-detection, outcome recommendation, and (new this
packet) evidence search. Each shows its own clearly-captioned fallback
behavior. A future packet activates them one at a time against a real
key.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from theoretical.hypothesis_extraction.scanner import scan_dossier
from theoretical.hypothesis_extraction.ranking import rank_hypotheses
from theoretical.evidence_gathering.agent import gather_evidence
from theoretical.evidence_gathering.review import build_evidence_update_trigger
from theoretical.dossier_versioning.version import build_new_version
from theoretical.simulation.parameter_extraction import (
    apply_founder_overrides,
    extract_parameters,
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
)
from theoretical.decision.ceiling import compute_ceiling
from theoretical.decision.kill_criteria import get_kill_criteria_text
from theoretical.decision.outcome import recommend_outcome, verify_decision_acceptance

EVIDENCE_ICONS = {
    "CONFIRMED": "✅",       # same five icons as Idea Dossier
    "ESTIMATE": "\U0001F4CA",
    "FOUNDER_OPINION": "\U0001F5E3️",
    "ASSUMPTION": "⚠️",
    "UNKNOWN": "❓",
}

OUTCOME_ICONS = {
    "SURVIVES": "✅",       # same check mark as CONFIRMED, deliberately -- both mean "no concern"
    "DEGRADED": "⚠️",  # same warning triangle as ASSUMPTION, deliberately -- both mean "caution"
    "BREAKS": "\U0001F534",      # red circle -- distinct from any evidence icon, reads as "stop"
    "NOT_EVALUABLE": "❓",   # same question mark as UNKNOWN, deliberately -- both mean "no answer available"
}

EVIDENCE_SEARCH_ICONS = {
    "FOUND": "\U0001F50E",
    "NO_EVIDENCE_FOUND": "❓",
    "NOT_SEARCHED": "⏳",
}

DECISION_ICONS = {
    "Reject": "\U0001F534",              # red circle -- same as stress-test BREAKS, both mean "stop"
    "Hold": "⏸️",              # pause
    "Reformulate": "\U0001F504",         # cycle arrows
    "Pass with Conditions": "⚠️",  # same warning triangle as ASSUMPTION/DEGRADED -- "caution, not clear"
    "Advance": "✅",                 # same check mark as CONFIRMED/SURVIVES -- "clear"
}


def _no_llm_probe_call(spec: dict) -> str:
    """
    Deterministic baseline stub (see module header). Always returns
    an empty string, which run_qualitative_probe's own guard clause
    turns into status="FAILED" for every generated test -- visible,
    not hidden, same "FAILED over silent loss" doctrine as every
    other guard in this codebase.
    """
    return ""


def _no_llm_recommendation_call(payload: dict) -> str:
    """
    Deterministic baseline stub. Always returns an empty string;
    recommend_outcome()'s own guard clause turns this into a
    clearly-labeled status="FALLBACK_REJECT", citing the ceiling's
    own real triggers as evidence.
    """
    return ""


def _no_llm_evidence_call(hypotheses: list) -> str:
    """
    Deterministic baseline stub for live evidence search. Always
    returns an empty string, which apply_evidence_search_guards()
    turns into search_status="NOT_SEARCHED" for every hypothesis --
    visible, not hidden. The Mock Proposals toggle below exists
    specifically so this screen has something demonstrable without a
    live key (see this packet's header, requirement #4).
    """
    return ""


# Registered acceptance numbers -- phase1_decisions_log.md (P1.0.2 / P1.0.3).
# Only valid at working_dossier version 1 -- see this packet's §0(b).
KNOWN_ACCEPTANCE = {
    "DS-0FE02838.json": {"total": 13, "claim": 13, "unknown": 0},
    "DS-SYNTH-PARTIAL.json": {"total": 13, "claim": 8, "unknown": 5},
}

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

st.set_page_config(page_title="VDVE - Theoretical Validation Cycle", layout="wide")
st.title("VDVE - Theoretical Validation Cycle (P1.1/P1.2)")

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
# Resets only when a DIFFERENT dossier_id is loaded -- switching fixtures
# or uploading a new file starts a fresh working copy. Persists across
# reruns for the SAME dossier_id, so evidence approvals survive button
# clicks and page reruns within one session. See this packet's header.
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

# --- Step 1: Scanner (operates on working_dossier, not the raw loaded file) ---
scan_result = scan_dossier(working_dossier)

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
        f"evidence, see Section 3) -- the original v1 acceptance numbers no longer "
        f"apply by design (an upgraded-to-CONFIRMED field correctly leaves the "
        f"hypothesis pool, P1.0.2). Actual: "
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
    }
    for h in scan_result.hypotheses
]
st.dataframe(hyp_rows, use_container_width=True)
st.caption(f"Excluded fields (EXTRACTION_EXCLUSIONS): {scan_result.excluded_fields}")

# --- Step 3: Ranking ---
st.subheader("2. Ranking (risk x uncertainty)")
claims_ranked, unknowns_ranked = rank_hypotheses(scan_result.hypotheses, llm_call=None)

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Claims** (ranked by `rank_score`, feed simulation/stress tests)")
    st.dataframe(
        [
            {
                "rank": h.rank, "field": h.source_field,
                "risk": h.risk_score, "uncertainty": h.uncertainty_score,
                "rank_score": h.rank_score,
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
                "rank_score": h.rank_score,
            }
            for h in unknowns_ranked
        ],
        use_container_width=True,
    )

# --- Step 4: Evidence Search / Evidence Review (P1.0.9, Packet #13 retrofit) ---
st.subheader("3. Evidence Search / Evidence Review")

all_hyps_for_search = claims_ranked + unknowns_ranked
current_hyp_ids = {h.source_field for h in all_hyps_for_search}

use_mock = st.checkbox(
    "Load mock evidence proposals (demo -- zero cost, no API key)",
    value=True,
    key=f"use_mock_{working_dossier['dossier_id']}",
)

if use_mock:
    with open(FIXTURES_DIR / "mock_evidence_proposals.json", encoding="utf-8") as f:
        mock_proposals = json.load(f)
    proposals = [p for p in mock_proposals if p["hypothesis_id"] in current_hyp_ids]
    st.caption(
        "Showing hand-authored mock proposals (fixtures/mock_evidence_proposals.json), "
        "filtered to hypotheses still present in the current working Dossier -- proves "
        "the full approve -> vN+1 -> re-extraction loop with zero cost and no API key. "
        "Uncheck to see the real (currently no-LLM-wired) evidence search pipeline."
    )
else:
    evidence_results = gather_evidence(
        all_hyps_for_search, working_dossier.get("version", 1), llm_call=_no_llm_evidence_call
    )
    proposals = [asdict(r) for r in evidence_results]
    st.caption(
        "Deterministic baseline mode (no LLM wired into this screen yet, same "
        "convention as every other screen) -- every proposal below shows "
        "search_status=NOT_SEARCHED until a future packet wires the live "
        "web-search agent in with a real ANTHROPIC_API_KEY."
    )

approved_ids = set()
if not proposals:
    st.info("No evidence proposals for the current hypothesis pool.")
for p in proposals:
    icon = EVIDENCE_SEARCH_ICONS.get(p["search_status"], "")
    with st.expander(f"{icon} {p['hypothesis_id']} -- {p['search_status']}"):
        if p["search_status"] == "FOUND":
            st.write(f"**Proposed value:** {p['proposed_value']}")
            st.write(f"**Proposed evidence_label:** {p['proposed_evidence_label']}")
            st.write(f"**Source:** {p['source']}")
            st.write(f"**Grounding excerpt:** {p['citation_excerpt']}")
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
        st.session_state.pop("approved_params", None)  # stale against the new version, see §0(c)
        st.success(
            f"Applied {len(trigger['updates'])} approved proposal(s). "
            f"New version: v{result['dossier']['version']}."
        )
        st.rerun()
    else:
        st.info("No proposals were approved -- nothing to apply, no new version written.")

# --- Step 5: Parameter Extraction + Review ---
st.subheader("4. Parameter Extraction + Review")
extracted = extract_parameters(working_dossier, llm_call=None)
st.caption(
    "Deterministic baseline mode (no LLM wired into this page yet) -- "
    "every parameter below is MISSING until you fill it in and approve. "
    "This is the real Parameter Review screen, not a placeholder."
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
            key=f"param_{param}_{dossier_filename}_v{working_dossier['version']}",
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
                "test_id": r.test_id,
                "category": r.category,
                "shocked_param": r.shocked_param,
                "multiplier": r.shock_multiplier,
                "affected_metric": r.affected_metric,
                "value": r.metric_value,
                "outcome": f"{OUTCOME_ICONS.get(r.outcome, '')} {r.outcome}",
            }
            for r in fixed_results
        ],
        use_container_width=True,
    )

    st.markdown("**Generated tests** (top-3 ranked claims, qualitative probes)")
    st.caption(
        "Deterministic baseline mode (no LLM wired into this screen yet, "
        "same convention as Parameter Extraction and Ranking above) -- "
        "every generated test below shows status=FAILED until a future "
        "packet wires the probe LLM in. This is the real Generated Test "
        "list, not a placeholder -- test_id, category, target hypothesis, "
        "and overlap with the fixed library are all real, computed data."
    )
    generated_specs = generate_test_specs(claims_ranked, n=3)
    generated_results = [
        run_qualitative_probe(spec, llm_call=_no_llm_probe_call) for spec in generated_specs
    ]
    st.dataframe(
        [
            {
                "test_id": r.test_id,
                "category": r.category,
                "target_hypothesis_id": r.target_hypothesis_id,
                "overlaps_with_fixed": ", ".join(r.overlaps_with_fixed) or "none",
                "status": r.status,
                "severity": r.severity or "-",
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
        st.caption(
            "Automated detection not wired into this screen yet -- read the "
            "text above yourself and classify it."
        )
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
    st.caption(
        "Deterministic baseline mode (no LLM wired into this screen yet, same "
        "convention as every other screen) -- the recommendation always "
        "degrades to a system-generated Reject (status=FALLBACK_REJECT), "
        "citing the ceiling's own triggers as evidence."
    )
    recommendation = recommend_outcome(
        ceiling_result, claims_ranked, all_stress_results, llm_call=_no_llm_recommendation_call
    )
    st.write(
        f"{DECISION_ICONS.get(recommendation['outcome'], '')} "
        f"**{recommendation['outcome']}** ({recommendation['status']})"
    )
    st.json(recommendation["payload"])

    valid_refs = {h.source_field for h in claims_ranked} | {r.test_id for r in all_stress_results}
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
    st.caption(
        "This export is the seed of the P1.2 Stress Test input contract -- "
        "the first full run's artifact, saved."
    )
