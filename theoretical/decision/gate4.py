"""
Gate 4 deterministic checklist (P1.0.8 + Amendment A1's criterion 9).
Every check re-derives its own answer from the cycle record's stored
artifacts and/or the current dossier -- never trusts a claim already
embedded in the recommendation payload (same re-derivation doctrine
as every prior packet, see phase1_decisions_log.md P1.0.8 rationale).

compute_gate4_verdict() computes; it never acts. BLOCK routing to
Hold (P1.0.8(a)) and founder sign-off (P1.0.8(c)) are both UI-layer
responsibilities (Packet #17) -- this module only reports what
*would* happen.
"""

from __future__ import annotations

from datetime import datetime, timezone

from theoretical.dossier_versioning.readiness import compute_readiness

ADVANCE_ELIGIBLE_OUTCOMES = frozenset({"Pass with Conditions", "Advance"})


def _check(criterion: int, check_id: str, description: str, passed: bool, applicable: bool, evidence: dict) -> dict:
    return {
        "criterion": criterion,
        "id": check_id,
        "description": description,
        "applicable": applicable,
        "passed": passed if applicable else True,  # not-applicable checks never block the gate on their own
        "evidence": evidence,
    }


def compute_gate4_verdict(cycle_record: dict, current_dossier: dict) -> dict:
    """
    Returns a Gate4Verdict dict:
      {"result": "PASS"|"BLOCK", "checks": [9 check dicts],
       "reason_codes": [str, ...], "block_routes_to": {...}|None,
       "founder_signoff": None, "checked_at": str,
       "chain_fingerprint": {...}}
    """
    checks: list[dict] = []
    outcome = cycle_record["recommendation"]["outcome"]
    current_version = current_dossier.get("version", 1)
    stress_results = cycle_record["stress_test_results"]
    hyp_ids = set(cycle_record["claim_field_codes"]) | set(cycle_record["unknown_field_codes"])

    # 1. outcome must be Pass with Conditions or Advance
    checks.append(_check(
        1, "outcome_in_advance_range",
        "Theoretical Cycle Record outcome is Pass with Conditions or Advance",
        outcome in ADVANCE_ELIGIBLE_OUTCOMES, True,
        {"outcome": outcome},
    ))

    # 2. no staleness -- full strictness, P1.0.8(b)
    version_current = cycle_record["dossier_version"] == current_version
    checks.append(_check(
        2, "version_current",
        "Evaluated dossier_version equals the current latest version",
        version_current, True,
        {"evaluated_version": cycle_record["dossier_version"], "current_version": current_version},
    ))

    # 3. readiness interlock, re-verified on the CURRENT dossier, not the frozen record
    current_readiness = compute_readiness(current_dossier)
    checks.append(_check(
        3, "mandatory_passed_current",
        "Current dossier's mandatory fields are all present and non-UNKNOWN",
        current_readiness["mandatory_passed"], True,
        {"mandatory_missing": current_readiness["mandatory_missing"]},
    ))

    # 4. Pass with Conditions only -- every condition references a real hypothesis
    is_pwc = outcome == "Pass with Conditions"
    conditions = cycle_record["recommendation"]["payload"].get("conditions", []) if is_pwc else []
    conditions_valid = all(c.get("hypothesis_id") in hyp_ids for c in conditions) if is_pwc else True
    checks.append(_check(
        4, "conditions_reference_real_hypotheses",
        "Every Pass with Conditions item resolves to a real hypothesis_id",
        conditions_valid, is_pwc,
        {"conditions": conditions},
    ))

    # 5. Advance only -- re-derive zero BREAKS from the stored results (broadened from
    #    "top-N" to the full set -- see this packet's §0(b), a strictly stronger check
    #    that matches what compute_ceiling() itself already guarantees).
    is_advance = outcome == "Advance"
    breaks = [r["test_id"] for r in stress_results if r.get("outcome") == "BREAKS"] if is_advance else []
    checks.append(_check(
        5, "no_breaks_if_advance",
        "Zero stress tests BREAK, independently re-derived from stored results",
        not breaks, is_advance,
        {"breaking_tests": breaks},
    ))

    # 6. every referenced stress test completed
    incomplete = [r["test_id"] for r in stress_results if r.get("status") != "COMPLETED"]
    checks.append(_check(
        6, "all_tests_completed",
        "Every referenced stress test has status == COMPLETED",
        not incomplete, True,
        {"incomplete_tests": incomplete},
    ))

    # 7. no open kill-criteria alert awaiting founder response
    kill_open = cycle_record["kill_status"] == "Possible match (unconfirmed)"
    checks.append(_check(
        7, "no_open_kill_alert",
        "No unresolved Kill Criteria Match Alert",
        not kill_open, True,
        {"kill_status": cycle_record["kill_status"]},
    ))

    # 8. full-chain referential consistency -- every generated probe's target
    #    hypothesis exists in the same hypothesis pool the decision evaluated
    orphaned = [
        r["test_id"] for r in stress_results
        if r.get("target_hypothesis_id") is not None and r["target_hypothesis_id"] not in hyp_ids
    ]
    checks.append(_check(
        8, "full_chain_referential_consistency",
        "Every generated test's target hypothesis exists in the evaluated hypothesis pool",
        not orphaned, True,
        {"orphaned_tests": orphaned},
    ))

    # 9. Amendment A1 -- unknowns must be fully accounted for
    unknown_ids = set(cycle_record["unknown_field_codes"])
    if is_advance:
        a1_pass = len(unknown_ids) == 0
        a1_evidence = {"unknown_field_codes": sorted(unknown_ids)}
    elif is_pwc:
        referenced = {c.get("hypothesis_id") for c in conditions}
        missing = unknown_ids - referenced
        a1_pass = not missing
        a1_evidence = {"unknowns_missing_from_conditions": sorted(missing)}
    else:
        a1_pass, a1_evidence = True, {}
    checks.append(_check(
        9, "unknowns_accounted_for",
        "Advance requires zero unknowns; Pass with Conditions requires every unknown in conditions[]",
        a1_pass, is_advance or is_pwc,
        a1_evidence,
    ))

    all_passed = all(c["passed"] for c in checks)
    reason_codes = [c["id"] for c in checks if not c["passed"]]

    return {
        "result": "PASS" if all_passed else "BLOCK",
        "checks": checks,
        "reason_codes": reason_codes,
        "block_routes_to": None if all_passed else {"outcome": "Hold", "hold_origin": "gate_procedural"},
        "founder_signoff": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "chain_fingerprint": {
            "dossier_version": cycle_record["dossier_version"],
            "cycle_record_id": cycle_record["cycle_record_id"],
            "claim_field_codes": cycle_record["claim_field_codes"],
            "unknown_field_codes": cycle_record["unknown_field_codes"],
        },
    }
