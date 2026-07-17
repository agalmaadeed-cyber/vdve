"""
Evidence Review approval glue (P1.0.9 point 1, completed by this
packet). Connects an EvidenceProposal batch + a founder's approved
subset to Packet #11's build_new_version() "evidence_update" trigger
contract, unchanged. This is the ONLY path by which an evidence
proposal ever becomes a real Dossier value -- Rule 6, restated: no
upgrade authority anywhere except through explicit founder approval,
enforced here by requiring both proposal.search_status == "FOUND"
AND membership in approved_ids before a proposal contributes
anything to the resulting trigger.
"""

from __future__ import annotations


def build_evidence_update_trigger(proposals: list[dict], approved_ids: set[str]) -> dict:
    """
    proposals: list of EvidenceProposal-shaped dicts (hypothesis_id,
    search_status, proposed_value, proposed_evidence_label, source,
    ...). approved_ids: the set of hypothesis_id strings the founder
    approved.

    A proposal only contributes an update if BOTH its own
    search_status == "FOUND" (there is an actual value to write) AND
    its hypothesis_id is in approved_ids (the founder said yes) --
    approving (or accidentally including) a NO_EVIDENCE_FOUND or
    NOT_SEARCHED proposal's id is a no-op, never an error, since there
    is nothing there to approve.

    Returns a theoretical.dossier_versioning.version-shaped
    "evidence_update" trigger dict, ready to pass to
    build_new_version() unchanged. If nothing was approved, "updates"
    is an empty list -- the CALLER's responsibility to skip calling
    build_new_version() in that case (never bump a version for a
    no-op change -- see this packet's own app.py wiring, §5).
    """
    updates = []
    for p in proposals:
        if p.get("hypothesis_id") in approved_ids and p.get("search_status") == "FOUND":
            updates.append({
                "field": p["hypothesis_id"],
                "new_value": p.get("proposed_value"),
                "new_evidence_label": p.get("proposed_evidence_label"),
                "source": p.get("source"),
            })
    return {"type": "evidence_update", "updates": updates}
