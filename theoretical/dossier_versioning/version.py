"""
Dossier vN+1 construction (P1.0.7). Pure, storage-agnostic -- returns
a new Dossier dict; never writes to any database (this packet's own
scope, see header). Never mutates the input dossier.

Two legal trigger types (P1.0.7b), enforced in code, never trusted
from caller-supplied data beyond these two literal strings:
- "reformulation": reformulation_targets = [{"field": field_code,
  "guidance": str}, ...] -- from a Reformulate outcome (Packet #9).
  Always resets the target field to UNKNOWN (see this packet's §0(b)
  for why the "arrives with a fresh label" branch never applies here).
- "evidence_update": updates = [{"field": field_code, "new_value": str,
  "new_evidence_label": str, "source": str}, ...] -- from a future
  evidence-gathering agent (P1.0.9), always carries a genuine
  replacement value + documented source, so it DOES earn a fresh,
  non-UNKNOWN label (P1.0.7c's other branch).

Every targeted field reference that doesn't resolve to a real
field_code in the dossier is a declared failure -- recorded in
rejected_changes, never silently dropped, never invented.
"""

from __future__ import annotations

from datetime import datetime, timezone

from theoretical.dossier_versioning.readiness import compute_readiness

LEGAL_TRIGGERS = frozenset({"reformulation", "evidence_update"})


def _find_field(dossier: dict, field_code: str):
    for section_fields in dossier.get("sections", {}).values():
        for field_obj in section_fields.values():
            if field_obj.get("field_code") == field_code:
                return field_obj
    return None


def build_new_version(dossier: dict, trigger: dict, now: str | None = None) -> dict:
    """
    Returns {"dossier": <new dossier dict>, "rejected_changes": [...]}.

    trigger = {"type": "reformulation"|"evidence_update", ...payload}.
    An unrecognized trigger type raises ValueError -- this is a
    programming-contract violation (only Packets #9/#future-P1.0.9
    construct trigger dicts), not a founder-facing data error, so it
    is not silently degraded like an LLM guard clause would be.
    """
    if trigger.get("type") not in LEGAL_TRIGGERS:
        raise ValueError(f"Illegal trigger type: {trigger.get('type')!r}. Must be one of {sorted(LEGAL_TRIGGERS)}.")

    timestamp = now or datetime.now(timezone.utc).isoformat()
    new_dossier = json_deep_copy(dossier)
    change_log: list[dict] = []
    rejected_changes: list[dict] = []

    if trigger["type"] == "reformulation":
        for target in trigger.get("reformulation_targets", []):
            field_code = target.get("field")
            field_obj = _find_field(new_dossier, field_code)
            if field_obj is None:
                rejected_changes.append({"field": field_code, "reason": "field_code not found in dossier"})
                continue

            change_log.append({
                "field": field_code,
                "before_value": field_obj.get("value"),
                "before_label": field_obj.get("evidence_label"),
                "after_value": "",
                "after_label": "UNKNOWN",
                "trigger": "reformulation",
                "rationale": target.get("guidance"),
            })
            field_obj["value"] = ""
            field_obj["evidence_label"] = "UNKNOWN"
            field_obj["filled_by"] = "vdve_reformulation"
            field_obj["filled_at"] = timestamp
            # a.2 fix (cross-project evaluation, 2026-07-23): the field's
            # content is being wiped back to blank/UNKNOWN, so any prior
            # mock-evidence provenance no longer describes anything real --
            # clear it rather than leaving a stale True on an empty field.
            field_obj["is_mock_evidence"] = False

    elif trigger["type"] == "evidence_update":
        for update in trigger.get("updates", []):
            field_code = update.get("field")
            field_obj = _find_field(new_dossier, field_code)
            if field_obj is None:
                rejected_changes.append({"field": field_code, "reason": "field_code not found in dossier"})
                continue

            change_log.append({
                "field": field_code,
                "before_value": field_obj.get("value"),
                "before_label": field_obj.get("evidence_label"),
                "after_value": update.get("new_value"),
                "after_label": update.get("new_evidence_label"),
                "trigger": "evidence_update",
                "rationale": update.get("source"),
                "is_mock": bool(update.get("is_mock", False)),
            })
            field_obj["value"] = update.get("new_value")
            field_obj["evidence_label"] = update.get("new_evidence_label")
            field_obj["sources"] = list(field_obj.get("sources") or []) + [update.get("source")]
            field_obj["filled_by"] = "vdve_evidence_gathering"
            field_obj["filled_at"] = timestamp
            # a.2 fix (cross-project evaluation, 2026-07-23): persist the
            # update's mock/live origin directly onto the field, not just
            # in session-level UI state -- this is what lets a "MOCK" badge
            # stay durably visible in the Ranking table (and any future
            # per-field view) across every later version, not just at the
            # moment of approval.
            field_obj["is_mock_evidence"] = bool(update.get("is_mock", False))

    new_dossier["version"] = dossier.get("version", 1) + 1
    new_dossier["version_origin"] = "vdve"
    new_dossier["derived_from_version"] = dossier.get("version", 1)
    new_dossier["change_log"] = change_log
    new_dossier["readiness"] = compute_readiness(new_dossier, now=timestamp)

    return {"dossier": new_dossier, "rejected_changes": rejected_changes}


def json_deep_copy(obj):
    """Dependency-free deep copy -- avoids mutating the caller's dossier."""
    import copy
    return copy.deepcopy(obj)
