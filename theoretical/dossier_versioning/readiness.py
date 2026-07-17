"""
Readiness scoring (P1.0.7c) -- a faithful REIMPLEMENTATION of Idea
Dossier's own readiness.py, not a literal copy. The actual source
file is not present in this workspace (the Idea-Dossier repo is not
cloned here) -- see this packet's §0(a) for the full derivation and
the one flagged, unverified value (the non-passing status string).

Algorithm: every field is weighted x3 if mandatory, x1 if soft/
optional. A field's weight counts toward score_weighted only if its
evidence_label is not "UNKNOWN". score_percentage is that sum over
the fixed maximum (46 -- 7 mandatory x3 + 25 soft x1, reverse-derived
and verified byte-exact against DS-0FE02838.json's own recorded
readiness block, see §0(a)). mandatory_passed requires every
mandatory field to be present and non-UNKNOWN.
"""

from __future__ import annotations

from datetime import datetime, timezone

# idea_dossier_specification.md, Section 6.
MANDATORY_FIELDS: frozenset[str] = frozenset({"A1", "B1", "C1", "F1", "F2", "E2", "E3"})

MAX_WEIGHTED_SCORE = 46  # see this packet's §0(a) for the derivation
READINESS_THRESHOLD = 0.70


def compute_readiness(dossier: dict, now: str | None = None) -> dict:
    """
    Walks dossier["sections"] (this codebase's own idiom, same as
    scanner.py) and computes the readiness object. Never mutates the
    input dossier.
    """
    unknown_fields: list[str] = []
    mandatory_missing: list[str] = []
    score_weighted = 0

    for section_fields in dossier.get("sections", {}).values():
        for field_obj in section_fields.values():
            field_code = field_obj.get("field_code")
            if not field_code:
                continue
            is_mandatory = field_code in MANDATORY_FIELDS
            is_unknown = field_obj.get("evidence_label") == "UNKNOWN"

            if is_unknown:
                unknown_fields.append(field_code)
                if is_mandatory:
                    mandatory_missing.append(field_code)
            else:
                score_weighted += 3 if is_mandatory else 1

    score_percentage = round(score_weighted / MAX_WEIGHTED_SCORE * 100)
    mandatory_passed = not mandatory_missing
    status = "ready" if (mandatory_passed and score_percentage >= READINESS_THRESHOLD * 100) else "not_ready"

    return {
        "status": status,
        "threshold": READINESS_THRESHOLD,
        "computed_at": now or datetime.now(timezone.utc).isoformat(),
        "score_weighted": score_weighted,
        "unknown_fields": unknown_fields,
        "mandatory_passed": mandatory_passed,
        "score_percentage": score_percentage,
        "mandatory_missing": mandatory_missing,
    }
