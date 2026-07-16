"""
VDVE -- Theoretical Validation Cycle, minimal UI (P1.1).

No storage backend -- st.session_state only (P1.1 scope decision,
2026-07-16). Displays the full deterministic pipeline (Packets #1-#4)
wired together end-to-end: Dossier -> Hypothesis Extraction -> Ranking
-> Parameter Extraction -> (founder approval) -> Simulation.

The LLM phrasing layer (Packet #2) is intentionally NOT wired into
this page yet -- no ANTHROPIC_API_KEY dependency for this packet.
Parameter Extraction runs in its deterministic llm_call=None baseline
(everything MISSING until a future packet wires the LLM in), so every
parameter is filled in manually below -- this is the Parameter Review
screen's first real, working implementation, not a placeholder.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from theoretical.hypothesis_extraction.scanner import scan_dossier
from theoretical.hypothesis_extraction.ranking import rank_hypotheses
from theoretical.simulation.parameter_extraction import (
    apply_founder_overrides,
    extract_parameters,
)
from theoretical.simulation.unit_economics import (
    INDEPENDENTS,
    compute_metric_evidence_labels,
    compute_scenarios,
)

EVIDENCE_ICONS = {
    "CONFIRMED": "✅",       # same five icons as Idea Dossier
    "ESTIMATE": "\U0001F4CA",
    "FOUNDER_OPINION": "\U0001F5E3️",
    "ASSUMPTION": "⚠️",
    "UNKNOWN": "❓",
}

# Registered acceptance numbers -- phase1_decisions_log.md (P1.0.2 / P1.0.3)
KNOWN_ACCEPTANCE = {
    "DS-0FE02838.json": {"total": 13, "claim": 13, "unknown": 0},
    "DS-SYNTH-PARTIAL.json": {"total": 13, "claim": 8, "unknown": 5},
}

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

st.set_page_config(page_title="VDVE - Theoretical Validation Cycle", layout="wide")
st.title("VDVE - Theoretical Validation Cycle (P1.1)")

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

st.header(f"Dossier: {dossier.get('dossier_id', 'unknown')}")

# --- Step 1: Scanner ---
scan_result = scan_dossier(dossier)

# --- Live acceptance bar: the page itself is an acceptance test ---
if dossier_filename in KNOWN_ACCEPTANCE:
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

# --- Step 4: Parameter Extraction + Review ---
st.subheader("3. Parameter Extraction + Review")
extracted = extract_parameters(dossier, llm_call=None)
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
            key=f"param_{param}_{dossier_filename}", label_visibility="collapsed",
        )
        overrides[param] = {"value": val, "evidence_label": "FOUNDER_OPINION"}

if st.button("Approve Parameters"):
    st.session_state["approved_params"] = apply_founder_overrides(extracted, overrides)
    st.success("Parameters approved.")

approved = st.session_state.get("approved_params")

# --- Step 5: Simulation ---
scenarios = None
if approved:
    st.subheader("4. Simulation Scenarios")

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

# --- Step 6: Export ---
if scenarios:
    st.subheader("5. Export")
    export_data = {
        "dossier_id": dossier.get("dossier_id"),
        "hypotheses": {
            "claims": [asdict(h) for h in claims_ranked],
            "unknowns": [asdict(h) for h in unknowns_ranked],
        },
        "approved_parameters": approved,
        "scenarios": scenarios,
    }
    st.download_button(
        "Export JSON",
        data=json.dumps(export_data, indent=2, default=str, ensure_ascii=False),
        file_name=f"vdve_export_{dossier.get('dossier_id', 'unknown')}.json",
        mime="application/json",
    )
    st.caption(
        "This export is the seed of the P1.2 Stress Test input contract -- "
        "the first full run's artifact, saved."
    )
