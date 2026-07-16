"""
Parameter Extraction (P1.0.4): converts Dossier free text into the six
numeric independents `unit_economics.py` needs. LLM-assisted, governed
identically to the phrasing layer (Packet #2) -- identity check on
parameter name, any failure/absence -> "MISSING", never an invented
number.

FIELD_SOURCE_MAP is deterministic and explicit: which Dossier
field_codes each parameter is sourced from. `avg_customer_lifetime_months`
has no mapped source today -- it is unconditionally MISSING until a
Dossier field is designed to carry it (operational note, Amendment A2).

Parameter Review is represented here as `apply_founder_overrides()` --
a pure merge function. The eventual Streamlit screen (a later UI
packet) collects founder input and calls this same function; the
interface is fixed now so that packet only has to build a form around
it.
"""

from __future__ import annotations

import json
from typing import Callable

FIELD_SOURCE_MAP: dict[str, list[str]] = {
    "price_per_unit": ["D3", "D4"],
    "variable_cost_per_unit": ["D5"],
    "CAC": ["D6"],
    "avg_customer_lifetime_months": [],  # no reliable source field today
    "monthly_burn": ["D5"],
    "budget": ["E2"],
}

UNCERTAINTY_BY_LABEL: dict[str, int] = {
    "CONFIRMED": 0,
    "ESTIMATE": 1,
    "ASSUMPTION": 2,
    "FOUNDER_OPINION": 2,
    "UNKNOWN": 3,
}


def _find_field(dossier: dict, field_code: str) -> dict | None:
    for section in dossier["sections"].values():
        for f in section.values():
            if f["field_code"] == field_code:
                return f
    return None


def _worst_label(labels: list[str]) -> str:
    """Highest-uncertainty label wins when a parameter has multiple
    source fields with different evidence_labels -- the safer default."""
    if not labels:
        return "UNKNOWN"
    return max(labels, key=lambda l: UNCERTAINTY_BY_LABEL.get(l, 3))


def gather_extraction_inputs(dossier: dict) -> dict:
    """Deterministic, no LLM: collects raw text + evidence_label per
    parameter directly from the Dossier, before any interpretation."""
    inputs = {}
    for param, field_codes in FIELD_SOURCE_MAP.items():
        found = [_find_field(dossier, fc) for fc in field_codes]
        found = [f for f in found if f is not None]
        if not found:
            inputs[param] = {"raw_texts": [], "evidence_label": "UNKNOWN", "source_fields": []}
        else:
            inputs[param] = {
                "raw_texts": [f["value"] for f in found],
                "evidence_label": _worst_label([f["evidence_label"] for f in found]),
                "source_fields": field_codes,
            }
    return inputs


def extract_parameters(dossier: dict, llm_call: Callable | None = None) -> dict:
    """
    Returns {param: {"value": float|None, "evidence_label": str,
                      "extraction_status": "EXTRACTED"|"MISSING",
                      "source_fields": [...]}} for all six parameters,
    always -- every parameter appears, regardless of outcome.

    If llm_call is None (default -- this packet's zero-cost tested
    mode), every parameter with a source field is still attempted but
    yields no extraction (no interpretation happened), so everything
    is MISSING. This is a safe, fully deterministic baseline -- not a
    bug, the same "no LLM = safe fallback" pattern as Packets #2/#3.
    """
    inputs = gather_extraction_inputs(dossier)
    extractable = {p: v for p, v in inputs.items() if v["source_fields"]}

    raw_response = ""
    if llm_call is not None and extractable:
        try:
            raw_response = llm_call(extractable)
        except Exception:
            raw_response = ""

    try:
        parsed = json.loads(raw_response) if raw_response else []
        if not isinstance(parsed, list):
            raise ValueError("not an array")
    except (json.JSONDecodeError, ValueError):
        parsed = []

    extracted_values: dict[str, float] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("parameter_name")
        value = item.get("value")
        if (
            name in inputs
            and name not in extracted_values
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            extracted_values[name] = float(value)

    result = {}
    for param, info in inputs.items():
        if param in extracted_values:
            result[param] = {
                "value": extracted_values[param],
                "evidence_label": info["evidence_label"],
                "extraction_status": "EXTRACTED",
                "source_fields": info["source_fields"],
            }
        else:
            result[param] = {
                "value": None,
                "evidence_label": info["evidence_label"],
                "extraction_status": "MISSING",
                "source_fields": info["source_fields"],
            }
    return result


def apply_founder_overrides(extracted: dict, overrides: dict) -> dict:
    """
    Parameter Review data contract. `overrides`: {param: {"value": float,
    "evidence_label": str (optional, defaults to FOUNDER_OPINION)}}.
    Overridden parameters are marked "FOUNDER_CONFIRMED" -- distinct
    from "EXTRACTED", so the report can always show which numbers came
    from the model versus the founder directly.
    """
    result = {}
    for param, info in extracted.items():
        if param in overrides:
            ov = overrides[param]
            result[param] = {
                "value": ov["value"],
                "evidence_label": ov.get("evidence_label", "FOUNDER_OPINION"),
                "extraction_status": "FOUNDER_CONFIRMED",
                "source_fields": info["source_fields"],
            }
        else:
            result[param] = info
    return result
