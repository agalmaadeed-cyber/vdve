"""
Deterministic Hypothesis Extraction scanner.

Implements the SELECTION and CLASSIFICATION rules decided in P1.0.2,
and the COUNTING derived from them. This module performs no LLM call,
no network access, and produces no `statement` text — phrasing is a
separate, later stage (Implementation Packet #2). Every hypothesis
emitted here carries `phrasing_status = "PENDING"` and null scoring
fields, both filled in by later packets (#2 phrasing, #3 ranking).

Decisions this module implements:
- P1.0.2: selection (all non-CONFIRMED fields, minus EXTRACTION_EXCLUSIONS)
          and classification (hypothesis_type: "claim" vs "unknown").
- P1.0.1: no assumptions about Idea Dossier's own storage — this module
          only ever reads a clean, already-decoded Dossier dict (the
          handoff contract fixed by the fixture-extraction note in
          phase1_decisions_log.md, P1.0.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# P1.0.2, decision item 4: fields excluded from hypothesis extraction
# entirely. F1 = success_criteria, F2 = kill_criteria — founder-authority
# fields (the measuring rulers), never treated as testable market
# hypotheses. Documented in code, never a silent drop: excluded fields
# are recorded on ScanResult.excluded_fields.
EXTRACTION_EXCLUSIONS: frozenset[str] = frozenset({"F1", "F2"})

# All five evidence labels the Dossier schema recognizes
# (idea_dossier_specification.md, Section 2).
KNOWN_EVIDENCE_LABELS: frozenset[str] = frozenset(
    {"CONFIRMED", "ESTIMATE", "ASSUMPTION", "FOUNDER_OPINION", "UNKNOWN"}
)

# P1.0.2, decision item 3: hypothesis_type classification by evidence_label.
CLAIM_LABELS: frozenset[str] = frozenset({"ESTIMATE", "ASSUMPTION", "FOUNDER_OPINION"})
UNKNOWN_LABELS: frozenset[str] = frozenset({"UNKNOWN"})

HypothesisType = Literal["claim", "unknown"]


@dataclass
class Hypothesis:
    dossier_id: str
    dossier_version: int
    source_field: str          # field_code, e.g. "C2"
    source_section: str        # Dossier JSON section key, e.g. "solution"
    source_subfield: str       # Dossier JSON subfield key, e.g. "value"
    original_evidence_label: str
    raw_dossier_text: str
    hypothesis_type: HypothesisType

    # Deferred to later implementation packets — never populated here.
    statement: str | None = None
    phrasing_status: str = "PENDING"          # Packet #2 (P1.0.2 phrasing layer)
    risk_score: float | None = None           # Packet #3 (P1.0.3)
    uncertainty_score: float | None = None    # Packet #3 (P1.0.3)
    rank: int | None = None                   # Packet #3 (P1.0.3)


@dataclass
class ScanResult:
    dossier_id: str
    dossier_version: int
    hypotheses: list[Hypothesis]
    excluded_fields: list[str] = field(default_factory=list)
    total_dossier_fields: int = 0

    @property
    def total(self) -> int:
        return len(self.hypotheses)

    @property
    def claim_count(self) -> int:
        return sum(1 for h in self.hypotheses if h.hypothesis_type == "claim")

    @property
    def unknown_count(self) -> int:
        return sum(1 for h in self.hypotheses if h.hypothesis_type == "unknown")


def scan_dossier(dossier: dict) -> ScanResult:
    """
    Deterministic scan of a Dossier dict (P1.0.2 selection + classification).

    Walks every field in `dossier["sections"]`. For each field:
      - CONFIRMED fields are never hypotheses (skipped).
      - Fields in EXTRACTION_EXCLUSIONS are never hypotheses, but are
        recorded in `ScanResult.excluded_fields` — an explicit, visible
        exclusion, never a silent drop (P1.0.2 decision item 4).
      - Every remaining field becomes exactly one Hypothesis, typed
        "claim" (ESTIMATE/ASSUMPTION/FOUNDER_OPINION) or "unknown"
        (UNKNOWN).

    Raises ValueError on:
      - a field_code that appears more than once in the Dossier
        (malformed input — never silently deduplicated), or
      - an evidence_label outside the five known values.

    Both are structural integrity failures that must surface loudly,
    consistent with the guard-clause discipline used throughout
    MVP Studio (Idea Dossier Decision 2; P1.0.2 count/identity guards).
    """
    dossier_id = dossier["dossier_id"]
    dossier_version = dossier["version"]

    hypotheses: list[Hypothesis] = []
    excluded_fields: list[str] = []
    seen_field_codes: set[str] = set()
    total_dossier_fields = 0

    for section_key, section_fields in dossier["sections"].items():
        for subfield_key, field_obj in section_fields.items():
            total_dossier_fields += 1
            field_code = field_obj["field_code"]
            evidence_label = field_obj["evidence_label"]

            if field_code in seen_field_codes:
                raise ValueError(f"Duplicate field_code in Dossier: {field_code}")
            seen_field_codes.add(field_code)

            if evidence_label not in KNOWN_EVIDENCE_LABELS:
                raise ValueError(
                    f"Unknown evidence_label '{evidence_label}' on field {field_code}"
                )

            if evidence_label == "CONFIRMED":
                continue

            if field_code in EXTRACTION_EXCLUSIONS:
                excluded_fields.append(field_code)
                continue

            if evidence_label in CLAIM_LABELS:
                hypothesis_type: HypothesisType = "claim"
            elif evidence_label in UNKNOWN_LABELS:
                hypothesis_type = "unknown"
            else:  # pragma: no cover — unreachable given KNOWN_EVIDENCE_LABELS check
                raise ValueError(
                    f"evidence_label '{evidence_label}' on field {field_code} is "
                    "non-CONFIRMED but not classified as claim or unknown."
                )

            hypotheses.append(
                Hypothesis(
                    dossier_id=dossier_id,
                    dossier_version=dossier_version,
                    source_field=field_code,
                    source_section=section_key,
                    source_subfield=subfield_key,
                    original_evidence_label=evidence_label,
                    raw_dossier_text=field_obj.get("value", ""),
                    hypothesis_type=hypothesis_type,
                )
            )

    return ScanResult(
        dossier_id=dossier_id,
        dossier_version=dossier_version,
        hypotheses=hypotheses,
        excluded_fields=excluded_fields,
        total_dossier_fields=total_dossier_fields,
    )
