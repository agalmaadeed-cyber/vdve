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
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from theoretical.llm_utils import escape_markdown_dollar, compute_payload_hash
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
from theoretical.decision.cycle_record import build_cycle_record
from theoretical.decision.gate4 import compute_gate4_verdict
from venture_story.generator import generate_venture_story

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


def _display_status(real_status: str, is_live: bool) -> str:
    """
    Display-only override -- cross-project evaluation item a.1
    (2026-07-22). Several status fields (adjustment_status, stress-test
    status, extraction_status, recommendation status) reuse the exact
    same value ("FAILED"/"MISSING"/"FALLBACK_REJECT") both for "no live
    call has ever been attempted this session" and for "a live call was
    genuinely attempted and failed" -- indistinguishable on screen
    before any button was ever clicked. This helper ONLY changes what
    is rendered; it never touches the real status value stored on the
    object, which stays exactly what it was and keeps feeding
    compute_ceiling()/Gate 4/every other downstream consumer unchanged.
    Pass is_live=True only at the call site that is genuinely
    displaying a cached live result (Packet B's `found` flag); every
    other path (flag off, or flag on but not yet run this session)
    passes is_live=False and gets the neutral "NOT_RUN" label instead.
    """
    return real_status if is_live else "NOT_RUN"


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


def _llm_step_cache_key(step_name: str, dossier_id: str, dossier_version: int, payload_for_hash) -> str:
    return f"{step_name}:{dossier_id}:v{dossier_version}:{compute_payload_hash(payload_for_hash)}"


def _get_cached_llm_step(step_name: str, dossier_id: str, dossier_version: int, payload_for_hash):
    """
    Session-state-backed cache lookup -- Packet B's cost-redundancy
    fix (P1.4 Packet #2). Returns (result, found: bool). A hit means
    these EXACT inputs already produced a live result this session --
    no API call needed. A miss means the caller must show an explicit
    run button and wait for a click; it must NEVER call the API
    automatically, since automatic-on-every-rerun is precisely the
    behavior this packet exists to remove (see phase1_decisions_log.md
    and p1.4_packet_02_llm_call_deduplication.md S0).
    """
    cache = st.session_state.setdefault("llm_step_cache", {})
    key = _llm_step_cache_key(step_name, dossier_id, dossier_version, payload_for_hash)
    if key in cache:
        return cache[key], True
    return None, False


def _store_cached_llm_step(
    step_name: str, dossier_id: str, dossier_version: int, payload_for_hash, result, api_calls_made: int = 1
) -> None:
    """
    api_calls_made lets a step that fans out into multiple real API
    calls in one click (only run_qualitative_probe does this -- one
    call per generated spec, up to 3) report its true count. Every
    other step makes exactly one call per click, the default.
    """
    cache = st.session_state.setdefault("llm_step_cache", {})
    key = _llm_step_cache_key(step_name, dossier_id, dossier_version, payload_for_hash)
    cache[key] = result
    st.session_state["api_call_count"] = st.session_state.get("api_call_count", 0) + api_calls_made


# Registered acceptance numbers -- phase1_decisions_log.md (P1.0.2 / P1.0.3).
# Only valid at working_dossier version 1 -- see Packet #13's §0(b).
KNOWN_ACCEPTANCE = {
    "DS-0FE02838.json": {"total": 13, "claim": 13, "unknown": 0},
    "DS-SYNTH-PARTIAL.json": {"total": 13, "claim": 8, "unknown": 5},
}

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

st.set_page_config(page_title="The Crucible - Theoretical Validation Cycle", layout="wide")
st.title("The Crucible - Theoretical Validation Cycle (P1.1/P1.2)")

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

st.sidebar.caption(f"API calls this session: {st.session_state.get('api_call_count', 0)}")

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
    phrasing_hash_payload = [
        {
            "field_code": h.source_field, "hypothesis_type": h.hypothesis_type,
            "source_section": h.source_section, "raw_text": h.raw_dossier_text,
        }
        for h in scan_result.hypotheses
    ]
    cached, found = _get_cached_llm_step(
        "phrasing", working_dossier["dossier_id"], working_dossier.get("version", 1), phrasing_hash_payload
    )
    if found:
        hypotheses_for_pipeline = cached
        st.caption("Live phrasing active -- using cached result (inputs unchanged since last live run).")
    else:
        st.info("Live phrasing: inputs changed (or first run this session) -- click to phrase live.")
        if st.button(
            "Run live phrasing",
            key=f"run_phrasing_{working_dossier['dossier_id']}_v{working_dossier.get('version', 1)}",
        ):
            hypotheses_for_pipeline = phrase_hypotheses(scan_result.hypotheses, llm_call=call_anthropic_phrasing)
            _store_cached_llm_step(
                "phrasing", working_dossier["dossier_id"], working_dossier.get("version", 1),
                phrasing_hash_payload, hypotheses_for_pipeline,
            )
            # a.10 fix (cross-project evaluation, 2026-07-24): an active,
            # ephemeral notification for this step's completion -- the
            # existing pattern was a silent st.rerun() with no signal at
            # all beyond the page re-rendering.
            st.toast("Hypothesis phrasing complete.", icon="✅")
            st.rerun()

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
ranking_live = False
if flag_risk_adj:
    ranking_hash_payload = [
        {"field_code": h.source_field, "section": h.source_section, "statement": h.statement or h.raw_dossier_text}
        for h in hypotheses_for_pipeline
    ]
    cached, found = _get_cached_llm_step(
        "risk_adjustment", working_dossier["dossier_id"], working_dossier.get("version", 1), ranking_hash_payload
    )
    if found:
        claims_ranked, unknowns_ranked = cached
        ranking_live = True
        st.caption("Live risk adjustment active -- using cached result (inputs unchanged since last live run).")
    else:
        st.info("Live risk adjustment: inputs changed (or first run this session) -- click to adjust live.")
        claims_ranked, unknowns_ranked = rank_hypotheses(hypotheses_for_pipeline, llm_call=None)
        if st.button(
            "Run live risk adjustment",
            key=f"run_risk_adj_{working_dossier['dossier_id']}_v{working_dossier.get('version', 1)}",
        ):
            claims_ranked, unknowns_ranked = rank_hypotheses(
                hypotheses_for_pipeline, llm_call=call_anthropic_risk_adjustment
            )
            _store_cached_llm_step(
                "risk_adjustment", working_dossier["dossier_id"], working_dossier.get("version", 1),
                ranking_hash_payload, (claims_ranked, unknowns_ranked),
            )
            # a.10 fix (cross-project evaluation, 2026-07-24): see phrasing above.
            st.toast("Risk adjustment (ranking) complete.", icon="✅")
            st.rerun()
else:
    claims_ranked, unknowns_ranked = rank_hypotheses(hypotheses_for_pipeline, llm_call=None)

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Claims** (ranked by `rank_score`, feed simulation/stress tests)")
    st.dataframe(
        [
            {
                "rank": h.rank, "field": h.source_field,
                "risk": h.risk_score, "uncertainty": h.uncertainty_score,
                "rank_score": h.rank_score,
                "adjustment_status": _display_status(h.adjustment_status, ranking_live),
                # a.2 fix (cross-project evaluation, 2026-07-23): persistent
                # mock-evidence badge -- survives every later version, not
                # just the moment of approval.
                "evidence": "🧪 MOCK" if h.is_mock_evidence else "",
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
                "adjustment_status": _display_status(h.adjustment_status, ranking_live),
                # a.2 fix (cross-project evaluation, 2026-07-23): persistent
                # mock-evidence badge -- survives every later version, not
                # just the moment of approval.
                "evidence": "🧪 MOCK" if h.is_mock_evidence else "",
            }
            for h in unknowns_ranked
        ],
        use_container_width=True,
    )

# --- Step 4: Evidence Search / Evidence Review ---
st.subheader("3. Evidence Search / Evidence Review")

all_hyps_for_search = claims_ranked + unknowns_ranked
current_hyp_ids = {h.source_field for h in all_hyps_for_search}

# a.2 fix (cross-project evaluation, 2026-07-23): default is now always
# False regardless of flag_evidence's state. Previously this defaulted to
# checked (True) whenever Live Evidence Search was off, which meant a
# founder could end up approving demo data into a real Dossier without
# ever having made an active choice to see mock data at all. Loading mock
# proposals is now always an explicit opt-in click, every time.
use_mock = st.checkbox(
    "Load mock evidence proposals (demo -- zero cost, no API key)",
    value=False,
    key=f"use_mock_{working_dossier['dossier_id']}",
)

if use_mock:
    with open(FIXTURES_DIR / "mock_evidence_proposals.json", encoding="utf-8") as f:
        mock_proposals = json.load(f)
    proposals = [p for p in mock_proposals if p["hypothesis_id"] in current_hyp_ids]
    st.caption(
        "🧪 Showing hand-authored mock proposals -- proves the full "
        "approve -> vN+1 -> re-extraction loop with zero cost and no API key. "
        "Any proposal you approve here is permanently tagged 🧪 MOCK on that field "
        "(visible in the Ranking table below) -- it never becomes indistinguishable "
        "from real evidence."
    )
elif flag_evidence:
    evidence_hash_payload = sorted(h.source_field for h in all_hyps_for_search)
    cached, found = _get_cached_llm_step(
        "evidence_search", working_dossier["dossier_id"], working_dossier.get("version", 1), evidence_hash_payload
    )
    if found:
        evidence_results = cached
        proposals = [asdict(r) for r in evidence_results]
        st.caption(
            "Live evidence search active -- using cached result (target hypotheses unchanged since the "
            "last successful search for this dossier version; no new web_search calls made)."
        )
    else:
        st.info(
            "Live evidence search: target hypotheses changed (or first search this session/version) "
            "-- click to search live (this calls the mandatory web_search tool)."
        )
        evidence_results = []
        proposals = []
        if st.button(
            "Run live evidence search",
            key=f"run_evidence_{working_dossier['dossier_id']}_v{working_dossier.get('version', 1)}",
        ):
            evidence_results = gather_evidence(
                all_hyps_for_search, working_dossier.get("version", 1), llm_call=call_anthropic_evidence_search
            )
            proposals = [asdict(r) for r in evidence_results]
            _store_cached_llm_step(
                "evidence_search", working_dossier["dossier_id"], working_dossier.get("version", 1),
                evidence_hash_payload, evidence_results,
            )
            # a.10 fix (cross-project evaluation, 2026-07-24): see phrasing above.
            st.toast("Evidence search complete.", icon="✅")
            st.rerun()
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
    trigger = build_evidence_update_trigger(proposals, approved_ids, is_mock=use_mock)
    if trigger["updates"]:
        result = build_new_version(working_dossier, trigger)
        st.session_state["working_dossier"] = result["dossier"]
        st.session_state.pop("approved_params", None)
        st.success(
            f"Applied {len(trigger['updates'])} approved proposal(s). "
            f"New version: v{result['dossier']['version']}."
        )
        # a.10 fix (cross-project evaluation, 2026-07-24): the st.success()
        # above is a persistent, page-embedded confirmation (stays visible
        # for this rerun cycle); the toast adds the same active, ephemeral
        # top-of-page signal used at every other completion point in this
        # app, for consistency.
        st.toast(f"Applied {len(trigger['updates'])} evidence proposal(s).", icon="✅")
        st.rerun()
    else:
        st.info("No proposals were approved -- nothing to apply, no new version written.")

# --- Step 5: Parameter Extraction + Review ---
st.subheader("4. Parameter Extraction + Review")
param_extraction_live = False
if flag_param_extraction:
    param_hash_payload = working_dossier.get("sections", {})
    cached, found = _get_cached_llm_step(
        "parameter_extraction", working_dossier["dossier_id"], working_dossier.get("version", 1), param_hash_payload
    )
    if found:
        extracted = cached
        param_extraction_live = True
        st.caption("Live extraction active -- using cached result (Dossier content unchanged since last live run).")
    else:
        st.info("Live extraction: Dossier content changed (or first run this session/version) -- click to extract live.")
        extracted = extract_parameters(working_dossier, llm_call=None)
        if st.button(
            "Run live parameter extraction",
            key=f"run_param_extraction_{working_dossier['dossier_id']}_v{working_dossier.get('version', 1)}",
        ):
            extracted = extract_parameters(working_dossier, llm_call=call_anthropic_parameter_extraction)
            _store_cached_llm_step(
                "parameter_extraction", working_dossier["dossier_id"], working_dossier.get("version", 1),
                param_hash_payload, extracted,
            )
            # a.10 fix (cross-project evaluation, 2026-07-24): see phrasing above.
            st.toast("Parameter extraction complete.", icon="✅")
            st.rerun()
else:
    extracted = extract_parameters(working_dossier, llm_call=None)
    st.caption("Deterministic baseline mode -- every parameter below shows NOT_RUN until a live extraction runs, or you fill it in yourself and approve.")

overrides = {}
param_cols = st.columns(len(INDEPENDENTS))
for i, param in enumerate(INDEPENDENTS):
    info = extracted[param]
    icon = EVIDENCE_ICONS.get(info["evidence_label"], "")
    with param_cols[i]:
        st.markdown(f"**{param}**")
        st.caption(f"{icon} {info['evidence_label']} | {_display_status(info['extraction_status'], param_extraction_live)}")
        st.caption(f"source: {info['source_fields'] or 'none'}")
        if info["extraction_status"] == "MISSING":
            st.warning("No value extracted -- enter a real estimate below, not the 0.0 default.")
        default_value = info["value"] if info["value"] is not None else 0.0
        val = st.number_input(
            f"value_{param}", value=float(default_value),
            # a.3 fix (cross-project evaluation, 2026-07-23): the key MUST
            # change when a genuine live extraction result becomes available
            # this session -- param_extraction_live, not flag_param_extraction.
            # flag_param_extraction stays True across the entire
            # "Run live parameter extraction" click+rerun (only the flag
            # toggle changes it), so keying on the flag alone left the
            # widget's key identical before and after a genuine live run --
            # Streamlit then reuses the OLD widget state (0.0, from the
            # pre-run baseline) and ignores the new `value=` default,
            # so the number box stayed stuck at 0.00 even though the
            # caption right above it correctly flipped to EXTRACTED.
            key=f"param_{param}_{dossier_filename}_v{working_dossier['version']}_{param_extraction_live}",
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
    generated_specs = generate_test_specs(claims_ranked, n=3)
    probes_live = False
    if flag_probes:
        probe_hash_payload = generated_specs
        cached, found = _get_cached_llm_step(
            "qualitative_probes", working_dossier["dossier_id"], working_dossier.get("version", 1), probe_hash_payload
        )
        if found:
            generated_results = cached
            probes_live = True
            st.caption("Live probes active -- using cached result (top-3 claims unchanged since last live run).")
        else:
            st.info("Live probes: top-3 claims changed (or first run this session) -- click to probe live.")
            generated_results = [
                run_qualitative_probe(spec, llm_call=_no_llm_probe_call) for spec in generated_specs
            ]
            if st.button(
                "Run live qualitative probes",
                key=f"run_probes_{working_dossier['dossier_id']}_v{working_dossier.get('version', 1)}",
            ):
                generated_results = [
                    run_qualitative_probe(spec, llm_call=call_anthropic_probe) for spec in generated_specs
                ]
                _store_cached_llm_step(
                    "qualitative_probes", working_dossier["dossier_id"], working_dossier.get("version", 1),
                    probe_hash_payload, generated_results, api_calls_made=len(generated_specs),
                )
                # a.10 fix (cross-project evaluation, 2026-07-24): see phrasing above.
                st.toast("Stress test probes complete.", icon="✅")
                st.rerun()
    else:
        st.caption("Deterministic baseline mode -- every generated test below shows status=NOT_RUN.")
        generated_results = [
            run_qualitative_probe(spec, llm_call=_no_llm_probe_call) for spec in generated_specs
        ]
    st.dataframe(
        [
            {
                "test_id": r.test_id, "category": r.category,
                "target_hypothesis_id": r.target_hypothesis_id,
                "overlaps_with_fixed": ", ".join(r.overlaps_with_fixed) or "none",
                "status": _display_status(r.status, probes_live), "severity": r.severity or "-",
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
        kill_status = "No concern"
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
    recommendation_live = False
    if flag_recommendation:
        recommendation_hash_payload = {
            "ceiling": ceiling_result["ceiling"],
            "ceiling_reasons": ceiling_result["triggered_by"],
            "claims": [
                {"field": h.source_field, "statement": h.statement or h.raw_dossier_text, "rank_score": h.rank_score}
                for h in claims_ranked
            ],
            "unknowns": [
                {"field": h.source_field, "statement": h.statement or h.raw_dossier_text} for h in unknowns_ranked
            ],
            "stress_tests": [
                {"test_id": r.test_id, "outcome_or_severity": r.outcome or r.severity or r.status}
                for r in all_stress_results
            ],
        }
        cached, found = _get_cached_llm_step(
            "recommendation", working_dossier["dossier_id"], working_dossier.get("version", 1),
            recommendation_hash_payload,
        )
        if found:
            recommendation = cached
            recommendation_live = True
            st.caption("Live recommendation active -- using cached result (ceiling/claims/stress tests unchanged since last live run).")
        else:
            st.info("Live recommendation: inputs changed (or first run this session) -- click to recommend live.")
            recommendation = recommend_outcome(
                ceiling_result, claims_ranked, all_stress_results, unknowns_ranked,
                llm_call=_no_llm_recommendation_call,
            )
            if st.button(
                "Run live recommendation",
                key=f"run_recommendation_{working_dossier['dossier_id']}_v{working_dossier.get('version', 1)}",
            ):
                recommendation = recommend_outcome(
                    ceiling_result, claims_ranked, all_stress_results, unknowns_ranked,
                    llm_call=call_anthropic_recommendation,
                )
                _store_cached_llm_step(
                    "recommendation", working_dossier["dossier_id"], working_dossier.get("version", 1),
                    recommendation_hash_payload, recommendation,
                )
                # a.10 fix (cross-project evaluation, 2026-07-24): see phrasing above.
                st.toast("Recommendation complete.", icon="✅")
                st.rerun()
    else:
        st.caption("Deterministic baseline mode -- not yet evaluated (falls back to Reject/NOT_RUN until a live recommendation runs).")
        recommendation = recommend_outcome(
            ceiling_result, claims_ranked, all_stress_results, unknowns_ranked,
            llm_call=_no_llm_recommendation_call,
        )
    st.write(
        f"{DECISION_ICONS.get(recommendation['outcome'], '')} **{recommendation['outcome']}** "
        f"({_display_status(recommendation['status'], recommendation_live)})"
    )
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

# --- Step 9: Gate 4 Check ---
st.session_state.setdefault("cycle_records", [])
st.session_state.setdefault("gate4_signoffs", {})

if approved and ceiling_result and recommendation:
    st.subheader("8. Gate 4 Check")
    st.caption(
        "Finalizing freezes a snapshot of this decision (P1.0.8's Theoretical "
        "Cycle Record) -- session-only, same as everything else in this app. "
        "You can finalize now and keep working the Dossier -- Gate 4 will "
        "correctly flag a stale record if you check it later."
    )

    if st.button("Finalize This Decision as a Cycle Record"):
        record = build_cycle_record(
            working_dossier, claims_ranked, unknowns_ranked, approved,
            all_stress_results, kill_status, ceiling_result, recommendation,
        )
        st.session_state["cycle_records"].append(record)
        st.success(f"Cycle record finalized: `{record['cycle_record_id'][:8]}` (dossier v{record['dossier_version']}).")
        # a.10 fix (cross-project evaluation, 2026-07-24): see evidence-review note above.
        st.toast("Cycle record finalized.", icon="✅")
        st.rerun()

    records = [
        r for r in st.session_state["cycle_records"]
        if r["dossier_id"] == working_dossier.get("dossier_id")
    ]
    if not records:
        st.info("No cycle records finalized yet for this dossier.")
    else:
        st.dataframe(
            [
                {
                    "id": r["cycle_record_id"][:8], "dossier_version": r["dossier_version"],
                    "outcome": r["recommendation"]["outcome"], "created_at": r["created_at"],
                    "signed_off": r["cycle_record_id"] in st.session_state["gate4_signoffs"],
                }
                for r in records
            ],
            use_container_width=True,
        )

        selected_id = st.selectbox(
            "Check a finalized cycle record against Gate 4",
            options=[r["cycle_record_id"] for r in records],
            format_func=lambda rid: rid[:8],
            index=len(records) - 1,
        )
        selected_record = next(r for r in records if r["cycle_record_id"] == selected_id)
        verdict = compute_gate4_verdict(selected_record, working_dossier)

        result_icon = "✅" if verdict["result"] == "PASS" else "\U0001F534"
        st.markdown(f"**Gate 4: {result_icon} {verdict['result']}**")
        st.dataframe(
            [
                {"#": c["criterion"], "check": c["id"], "applicable": c["applicable"], "passed": c["passed"]}
                for c in verdict["checks"]
            ],
            use_container_width=True,
        )
        with st.expander("Full check evidence (raw)"):
            st.json(verdict["checks"])

        if verdict["result"] == "BLOCK":
            st.error("Reason codes: " + ", ".join(verdict["reason_codes"]))
            st.caption(
                f"Routes to: {verdict['block_routes_to']['outcome']} "
                f"(hold_origin={verdict['block_routes_to']['hold_origin']})"
            )
        else:
            signed_off_at = st.session_state["gate4_signoffs"].get(selected_id)
            if signed_off_at:
                st.success(f"✅ Founder sign-off confirmed at {signed_off_at}.")
            else:
                st.warning(
                    "Gate 4 computes PASS deterministically -- activating it still "
                    "requires your sign-off (P1.0.8(c))."
                )
                if st.button("Confirm Gate 4 Sign-off", key=f"signoff_{selected_id}"):
                    st.session_state["gate4_signoffs"][selected_id] = datetime.now(timezone.utc).isoformat()
                    # a.10 fix (cross-project evaluation, 2026-07-24): this
                    # click is the ONE moment sign-off happens -- the
                    # st.success() a few lines above is a persistent,
                    # state-dependent display shown on every future page
                    # view of this record, not a one-time signal, so it
                    # alone doesn't satisfy "active notification of THIS
                    # completion." The toast fires exactly once, here.
                    st.toast("Gate 4 sign-off confirmed.", icon="✅")
                    st.rerun()

            if signed_off_at:
                st.markdown("---")
                st.download_button(
                    "Download Venture Story (.docx)",
                    data=generate_venture_story(
                        working_dossier, selected_record, verdict, signed_off_at, scenarios
                    ),
                    file_name=(
                        f"venture_story_{working_dossier.get('dossier_id', 'unknown')}"
                        f"_v{working_dossier.get('version')}.docx"
                    ),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                st.caption(
                    "A human-readable, printable narrative for a partner or investor -- "
                    "deterministic, no LLM involved (Decision P1.0.10)."
                )
else:
    st.info("Compute a theoretical decision above to finalize and check a cycle record.")

# --- Step 10: Export ---
if scenarios:
    st.subheader("9. Export")
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
        "cycle_records": [
            r for r in st.session_state.get("cycle_records", [])
            if r["dossier_id"] == working_dossier.get("dossier_id")
        ],
        "gate4_signoffs": st.session_state.get("gate4_signoffs", {}),
    }
    st.download_button(
        "Export JSON",
        data=json.dumps(export_data, indent=2, default=str, ensure_ascii=False),
        file_name=f"vdve_export_{working_dossier.get('dossier_id', 'unknown')}_v{working_dossier.get('version')}.json",
        mime="application/json",
    )
    st.caption("This export is the seed of the P1.2 Stress Test input contract -- the first full run's artifact, saved.")
