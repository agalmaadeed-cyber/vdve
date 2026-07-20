from venture_story.docx_renderer import BOLD_START, BOLD_END
from venture_story.markdown_builder import (
    _field_paragraph,
    _get_field,
    generate_intermediate_markdown,
)


def _make_field(field_code, value, evidence_label="ESTIMATE"):
    return {"field_code": field_code, "value": value, "evidence_label": evidence_label}


SMALL_DOSSIER = {
    "dossier_id": "DS-TEST",
    "version": 1,
    "sections": {
        "opportunity": {
            "problem": _make_field("A1", "Managers lose time to scattered tools."),
            "empty_field": _make_field("A2", ""),
        }
    },
}


def _full_field_set():
    """Every field_code the template quotes, each with a real value."""
    codes = (
        "A1", "A2", "A3", "A4", "A5",
        "C1", "C2", "C3", "C4", "C5",
        "B1", "B2", "B3", "B4", "B5", "B6", "B7",
        "D1", "D2", "D3", "D4", "D5", "D6",
        "F1", "F2", "F3", "F4",
    )
    return {code: _make_field(code, f"Value for {code}.") for code in codes}


def _build_full_dossier():
    fields = _full_field_set()
    return {
        "dossier_id": "DS-TEST",
        "version": 2,
        "source": {
            "uh_idea_name": "TestVenture",
            "uh_sector": "Productivity SaaS",
            "uh_final_score": "43/50",
            "uh_final_decision": "Test with reservations.",
            "uh_next_step": "Run a manual pilot first.",
        },
        "sections": {
            "opportunity": {"a1": fields["A1"], "a2": fields["A2"], "a3": fields["A3"], "a4": fields["A4"], "a5": fields["A5"]},
            "solution": {"c1": fields["C1"], "c2": fields["C2"], "c3": fields["C3"], "c4": fields["C4"], "c5": fields["C5"]},
            "customer_market": {
                "b1": fields["B1"], "b2": fields["B2"], "b3": fields["B3"], "b4": fields["B4"],
                "b5": fields["B5"], "b6": fields["B6"], "b7": fields["B7"],
            },
            "business_model": {"d1": fields["D1"], "d2": fields["D2"], "d3": fields["D3"], "d4": fields["D4"], "d5": fields["D5"], "d6": fields["D6"]},
            "success_definition": {"f1": fields["F1"], "f2": fields["F2"], "f3": fields["F3"], "f4": fields["F4"]},
        },
    }


def _build_cycle_record(outcome="Advance", conditions=None):
    payload = {"advance_confirmation": True} if outcome == "Advance" else {"conditions": conditions or []}
    return {
        "cycle_record_id": "cr-test-1",
        "dossier_id": "DS-TEST",
        "dossier_version": 2,
        "claim_field_codes": ["A1", "B1"],
        "unknown_field_codes": [],
        "approved_parameters": {},
        "stress_test_results": [
            {
                "test_id": "ST-01", "test_type": "quantitative_shock", "category": "cost",
                "source": "fixed_library", "status": "COMPLETED", "outcome": "SURVIVES",
                "target_hypothesis_id": None, "rationale": None, "severity": None,
            },
            {
                "test_id": "GEN-A1", "test_type": "qualitative_probe", "category": "demand",
                "source": "generated", "status": "COMPLETED", "outcome": None,
                "target_hypothesis_id": "A1", "rationale": "Plausible but unverified.", "severity": "MEDIUM",
            },
        ],
        "kill_status": "No concern",
        "ceiling_result": {"ceiling": outcome, "triggered_by": ["Pass with Conditions:stress_test_breaks:ST-04"] if outcome != "Advance" else []},
        "recommendation": {
            "outcome": outcome,
            "status": "LLM_RECOMMENDED",
            "narrative": "This is the recommendation narrative.",
            "payload": payload,
        },
    }


def _build_gate4_verdict(result="PASS"):
    return {
        "result": result,
        "checks": [
            {"criterion": 1, "id": "outcome_in_advance_range", "description": "Outcome in advance range", "applicable": True, "passed": True, "evidence": {}},
            {"criterion": 2, "id": "version_current", "description": "Version is current", "applicable": True, "passed": True, "evidence": {}},
        ],
        "reason_codes": [],
        "block_routes_to": None,
        "founder_signoff": None,
        "checked_at": "2026-07-20T00:00:00+00:00",
        "chain_fingerprint": {},
    }


def _build_scenarios():
    def _metrics(price):
        return {
            "price_per_unit": price, "variable_cost_per_unit": 0.02, "CAC": 20.0,
            "avg_customer_lifetime_months": 9.0, "monthly_burn": 30.0, "budget": 1000.0,
            "gross_margin": 0.999, "LTV": 215.82, "LTV_to_CAC": 10.79,
            "payback_period": 0.41, "runway_months": 33.33, "breakeven_customers": 0.61,
        }
    return {
        "conservative": _metrics(19.2),
        "base": _metrics(24.0),
        "optimistic": _metrics(28.8),
    }


SIGNED_OFF_AT = "2026-07-20T12:00:00+00:00"


# --- _get_field() / _field_paragraph() ---

def test_field_paragraph_present_field_with_value():
    result = _field_paragraph(SMALL_DOSSIER, "A1")
    assert result == f'{BOLD_START}The Problem:{BOLD_END} "Managers lose time to scattered tools." (Preliminary Estimate)'


def test_field_paragraph_present_field_with_empty_value():
    result = _field_paragraph(SMALL_DOSSIER, "A2")
    assert result == f"{BOLD_START}Who Faces It:{BOLD_END} Not yet determined."


def test_field_paragraph_absent_field_code():
    result = _field_paragraph(SMALL_DOSSIER, "Z9")
    assert result == f"{BOLD_START}Z9:{BOLD_END} Not present in this Dossier."


def test_get_field_never_raises_on_any_of_the_three_cases():
    assert _get_field(SMALL_DOSSIER, "A1") is not None
    assert _get_field(SMALL_DOSSIER, "A2") is not None
    assert _get_field(SMALL_DOSSIER, "Z9") is None


# --- generate_intermediate_markdown() smoke test ---

def test_all_eleven_section_headers_appear_in_order():
    dossier = _build_full_dossier()
    cycle_record = _build_cycle_record(outcome="Advance")
    gate4_verdict = _build_gate4_verdict()
    scenarios = _build_scenarios()

    markdown = generate_intermediate_markdown(dossier, cycle_record, gate4_verdict, SIGNED_OFF_AT, scenarios)

    headers = [f"## {i}." for i in range(1, 12)]
    positions = [markdown.index(h) for h in headers]
    assert positions == sorted(positions), "section headers are not in order"


def test_raw_evidence_label_never_appears_bare_while_translation_does():
    dossier = _build_full_dossier()
    cycle_record = _build_cycle_record(outcome="Advance")
    gate4_verdict = _build_gate4_verdict()
    scenarios = _build_scenarios()

    markdown = generate_intermediate_markdown(dossier, cycle_record, gate4_verdict, SIGNED_OFF_AT, scenarios)

    assert "ESTIMATE" not in markdown
    assert "Preliminary Estimate" in markdown


def test_raw_field_code_never_appears_as_a_label_in_body_text():
    dossier = _build_full_dossier()
    cycle_record = _build_cycle_record(outcome="Advance")
    gate4_verdict = _build_gate4_verdict()
    scenarios = _build_scenarios()

    markdown = generate_intermediate_markdown(dossier, cycle_record, gate4_verdict, SIGNED_OFF_AT, scenarios)

    # "A1" as a bold label (e.g. "**A1:**") must never appear -- only inside the
    # Appendix's audit-trail IDs (backtick-quoted technical references), which is fine.
    assert f"{BOLD_START}A1:{BOLD_END}" not in markdown


# --- Conditions block presence/absence ---

def test_pass_with_conditions_renders_conditions_block_with_hypothesis_id():
    dossier = _build_full_dossier()
    conditions = [{"hypothesis_id": "A1", "condition": "Validate demand via field interviews."}]
    cycle_record = _build_cycle_record(outcome="Pass with Conditions", conditions=conditions)
    gate4_verdict = _build_gate4_verdict()
    scenarios = _build_scenarios()

    markdown = generate_intermediate_markdown(dossier, cycle_record, gate4_verdict, SIGNED_OFF_AT, scenarios)

    assert "Conditions to resolve before full commitment" in markdown
    assert "(tied to `A1`)" in markdown


def test_advance_outcome_has_no_conditions_block():
    dossier = _build_full_dossier()
    cycle_record = _build_cycle_record(outcome="Advance")
    gate4_verdict = _build_gate4_verdict()
    scenarios = _build_scenarios()

    markdown = generate_intermediate_markdown(dossier, cycle_record, gate4_verdict, SIGNED_OFF_AT, scenarios)

    assert "Conditions to resolve before full commitment" not in markdown
