"""
Deterministic, zero-cost acceptance tests for Parameter Extraction
(P1.0.4). Uses the real DS-0FE02838.json fixture for field-sourcing
correctness -- not a simplified stand-in (Packet #3 lesson applied).
"""

import json
from pathlib import Path

from theoretical.simulation.parameter_extraction import (
    apply_founder_overrides,
    extract_parameters,
)

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def _load_dossier():
    with open(FIXTURES_DIR / "DS-0FE02838.json", encoding="utf-8") as f:
        return json.load(f)


def test_baseline_no_llm_call_everything_missing():
    result = extract_parameters(_load_dossier(), llm_call=None)
    assert all(v["extraction_status"] == "MISSING" for v in result.values())
    assert set(result.keys()) == {
        "price_per_unit", "variable_cost_per_unit", "CAC",
        "avg_customer_lifetime_months", "monthly_burn", "budget",
    }


def test_lifetime_has_no_source_field_always_missing():
    result = extract_parameters(_load_dossier(), llm_call=None)
    assert result["avg_customer_lifetime_months"]["source_fields"] == []
    assert result["avg_customer_lifetime_months"]["extraction_status"] == "MISSING"


def test_budget_evidence_label_sourced_correctly_from_e2():
    result = extract_parameters(_load_dossier(), llm_call=None)
    # DS-0FE02838's E2 (budget) is CONFIRMED (via interview_agent)
    assert result["budget"]["evidence_label"] == "CONFIRMED"


def test_stub_extraction_and_identity_guard():
    def stub_llm(_payload):
        return json.dumps(
            [
                {"parameter_name": "price_per_unit", "value": 29.0},
                {"parameter_name": "CAC", "value": 999},
                {"parameter_name": "not_a_real_param", "value": 5},  # invented, dropped
            ]
        )

    result = extract_parameters(_load_dossier(), llm_call=stub_llm)
    assert result["price_per_unit"]["extraction_status"] == "EXTRACTED"
    assert result["price_per_unit"]["value"] == 29.0
    assert result["CAC"]["extraction_status"] == "EXTRACTED"
    assert "not_a_real_param" not in result
    assert result["monthly_burn"]["extraction_status"] == "MISSING"  # not returned by stub


def test_malformed_llm_response_everything_missing():
    def broken_llm(_payload):
        return "not json {{{"

    result = extract_parameters(_load_dossier(), llm_call=broken_llm)
    assert all(v["extraction_status"] == "MISSING" for v in result.values())


def test_founder_override_marks_founder_confirmed():
    baseline = extract_parameters(_load_dossier(), llm_call=None)
    overridden = apply_founder_overrides(
        baseline, {"monthly_burn": {"value": 60.0, "evidence_label": "FOUNDER_OPINION"}}
    )
    assert overridden["monthly_burn"]["extraction_status"] == "FOUNDER_CONFIRMED"
    assert overridden["monthly_burn"]["value"] == 60.0
    assert overridden["price_per_unit"] == baseline["price_per_unit"]  # untouched
