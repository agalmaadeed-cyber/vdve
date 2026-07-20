"""
Eleven-section deterministic template (Decision P1.0.10). Every
sentence is either a fixed template string or a verbatim Dossier/
artifact quote -- no LLM, no free generation. generate_intermediate_
markdown() is explicitly the internal-only artifact (Decision point
2) -- never call it a "user export"; venture_story/generator.py is
the only caller, and it never writes this string to a file for the
founder to open directly.

Output is a small, genuine Markdown subset (headings via `# `/`## `,
paragraphs, GFM-style pipe tables) -- parsed by docx_renderer.py,
which is the only place bidi handling happens. This module never
worries about direction/script; it only assembles correct content in
the correct order, matching the founder's exact 11-section spec.
"""

from __future__ import annotations

from venture_story.docx_renderer import BOLD_START, BOLD_END
from venture_story.label_translation import (
    EVIDENCE_LABEL_TRANSLATION,
    FIELD_PROMPTS,
    KILL_STATUS_TRANSLATION,
    METRIC_LABELS,
    METRIC_ORDER,
    SEVERITY_TRANSLATION,
    STRESS_OUTCOME_TRANSLATION,
)


def _get_field(dossier: dict, field_code: str) -> dict | None:
    """
    Generic walker over dossier["sections"] by field_code -- the one
    reusable lookup every quoted field in this document goes through,
    for both Dossier value and its evidence_label (kill_criteria.py's
    get_kill_criteria_text() returns only the value, not the label
    this document also needs to show -- so this module does not reuse
    it, and reimplements the same walk generically instead, once).
    """
    for section_fields in dossier.get("sections", {}).values():
        for field_obj in section_fields.values():
            if field_obj.get("field_code") == field_code:
                return field_obj
    return None


def _field_paragraph(dossier: dict, field_code: str) -> str:
    prompt = FIELD_PROMPTS.get(field_code, field_code)
    field_obj = _get_field(dossier, field_code)
    if field_obj is None:
        return f"{BOLD_START}{prompt}:{BOLD_END} Not present in this Dossier."
    value = (field_obj.get("value") or "").strip()
    if not value:
        return f"{BOLD_START}{prompt}:{BOLD_END} Not yet determined."
    label = EVIDENCE_LABEL_TRANSLATION.get(
        field_obj.get("evidence_label"), field_obj.get("evidence_label", "")
    )
    return f'{BOLD_START}{prompt}:{BOLD_END} "{value}" ({label})'


def _fmt_metric(name: str, value: float | None) -> str:
    if value is None:
        return "Not available"
    if name == "gross_margin":
        return f"{value * 100:.1f}%"
    if name == "LTV_to_CAC":
        return f"{value:.2f}"
    return f"{value:,.2f}"


def _section_financial_table(scenarios: dict) -> list[str]:
    lines = ["| Metric | Conservative | Base | Optimistic |", "|---|---|---|---|"]
    for metric in METRIC_ORDER:
        row = [METRIC_LABELS[metric]]
        for scenario_name in ("conservative", "base", "optimistic"):
            row.append(_fmt_metric(metric, scenarios.get(scenario_name, {}).get(metric)))
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _section_stress_tests(cycle_record: dict) -> list[str]:
    results = cycle_record.get("stress_test_results", [])
    if not results:
        return ["No stress tests were recorded for this decision."]
    lines: list[str] = []
    for r in results:
        category = (r.get("category") or "").replace("_", " ").title()
        if r.get("test_type") == "quantitative_shock":
            outcome = STRESS_OUTCOME_TRANSLATION.get(r.get("outcome"), r.get("outcome") or "Unknown")
            lines.append(f"- {BOLD_START}{category}{BOLD_END} (numeric stress test): {outcome}.")
        else:
            severity = SEVERITY_TRANSLATION.get(r.get("severity"), r.get("severity") or "Unknown")
            rationale = (r.get("rationale") or "").strip()
            suffix = f" {rationale}" if rationale else ""
            lines.append(f"- {BOLD_START}{category}{BOLD_END} (qualitative review): {severity}.{suffix}")
    return lines


def _section_conditions(cycle_record: dict) -> list[str]:
    recommendation = cycle_record["recommendation"]
    if recommendation["outcome"] != "Pass with Conditions":
        return []
    conditions = recommendation["payload"].get("conditions", [])
    if not conditions:
        return []
    lines = ["", f"{BOLD_START}Conditions to resolve before full commitment:{BOLD_END}"]
    for c in conditions:
        lines.append(f"- (tied to `{c.get('hypothesis_id', '?')}`) {c.get('condition', '')}")
    return lines


def generate_intermediate_markdown(
    dossier: dict,
    cycle_record: dict,
    gate4_verdict: dict,
    signed_off_at: str,
    scenarios: dict,
) -> str:
    source = dossier.get("source", {}) or {}
    idea_name = source.get("uh_idea_name") or dossier.get("dossier_id", "This Venture")
    sector = source.get("uh_sector") or "an unspecified sector"
    recommendation = cycle_record["recommendation"]
    outcome = recommendation["outcome"]
    narrative = (recommendation.get("narrative") or "").strip()
    kill_status_reader = KILL_STATUS_TRANSLATION.get(cycle_record.get("kill_status"), cycle_record.get("kill_status", ""))

    lines: list[str] = []

    lines.append(f"# Venture Story — {idea_name}")
    lines.append("")

    # 1. Executive Summary
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(
        f'"{idea_name}" is a venture in {sector}. Following the Theoretical '
        f"Validation Cycle, this idea reached a Gate 4 {BOLD_START}{gate4_verdict['result']}{BOLD_END} "
        f"verdict, with a theoretical decision of {BOLD_START}{outcome}{BOLD_END}."
    )
    if narrative:
        lines.append("")
        lines.append(narrative)
    lines.append("")

    # 2. Idea Origin
    lines.append("## 2. Idea Origin")
    lines.append("")
    uh_score = source.get("uh_final_score", "not available")
    lines.append(f"This idea originated as a Unicorn Hunter evaluation in {BOLD_START}{sector}{BOLD_END}, scoring {BOLD_START}{uh_score}{BOLD_END}.")
    uh_decision = (source.get("uh_final_decision") or "").strip()
    if uh_decision:
        lines.append("")
        lines.append(f'Unicorn Hunter\'s verdict at that stage: "{uh_decision}"')
    lines.append("")

    # 3. Opportunity Definition
    lines.append("## 3. Opportunity Definition")
    lines.append("")
    for field_code in ("A1", "A2", "A3", "A4", "A5"):
        lines.append(_field_paragraph(dossier, field_code))
        lines.append("")

    # 4. Chosen Solution
    lines.append("## 4. Chosen Solution")
    lines.append("")
    for field_code in ("C1", "C2", "C3", "C4", "C5"):
        lines.append(_field_paragraph(dossier, field_code))
        lines.append("")

    # 5. Customer & Market
    lines.append("## 5. Customer & Market")
    lines.append("")
    for field_code in ("B1", "B2", "B3", "B4", "B5", "B6", "B7"):
        lines.append(_field_paragraph(dossier, field_code))
        lines.append("")

    # 6. Business Model
    lines.append("## 6. Business Model")
    lines.append("")
    for field_code in ("D1", "D2", "D3", "D4", "D5", "D6"):
        lines.append(_field_paragraph(dossier, field_code))
        lines.append("")

    # 7. Rigor Tested
    lines.append("## 7. Rigor Tested")
    lines.append("")
    ceiling_result = cycle_record.get("ceiling_result", {})
    triggered_by = ceiling_result.get("triggered_by") or []
    if triggered_by:
        lines.append(
            "This idea's outcome was capped by the following findings before any "
            "recommendation was made: " + "; ".join(triggered_by) + "."
        )
    else:
        lines.append("No stress-test or unresolved-unknown finding capped this idea's outcome.")
    lines.append("")
    lines.extend(_section_stress_tests(cycle_record))
    lines.append("")
    lines.append(f"{BOLD_START}Kill-Criteria Review:{BOLD_END} {kill_status_reader}.")
    lines.append("")

    # 8. Simplified Financial Snapshot
    lines.append("## 8. Simplified Financial Snapshot")
    lines.append("")
    lines.append(
        "The figures below are computed under three scenarios -- Conservative, "
        "Base, and Optimistic -- reflecting the uncertainty already recorded "
        "against each underlying input."
    )
    lines.append("")
    lines.extend(_section_financial_table(scenarios))
    lines.append("")

    # 9. Decision & Signature
    lines.append("## 9. Decision & Signature")
    lines.append("")
    lines.append(f"{BOLD_START}Theoretical Decision:{BOLD_END} {outcome}")
    lines.append("")
    lines.append(f"{BOLD_START}Gate 4 Verdict:{BOLD_END} {gate4_verdict['result']} (checked {gate4_verdict.get('checked_at', '')})")
    lines.append("")
    lines.append(f"{BOLD_START}Founder Sign-off:{BOLD_END} confirmed at {signed_off_at}")
    lines.extend(_section_conditions(cycle_record))
    lines.append("")

    # 10. Next Step / Call to Participate
    lines.append("## 10. Next Step / Call to Participate")
    lines.append("")
    uh_next_step = (source.get("uh_next_step") or "").strip()
    if uh_next_step:
        lines.append(f'Unicorn Hunter\'s original field-test recommendation for this idea: "{uh_next_step}"')
    else:
        lines.append("No field-test recommendation is on record for this idea.")
    lines.append("")

    # 11. Appendix
    lines.append("## 11. Appendix")
    lines.append("")
    lines.append("### Success and Kill Criteria")
    lines.append("")
    for field_code in ("F1", "F2", "F3", "F4"):
        lines.append(_field_paragraph(dossier, field_code))
        lines.append("")
    lines.append("### Audit Trail")
    lines.append("")
    lines.append(f"- Dossier ID: `{dossier.get('dossier_id', '')}`, version {dossier.get('version', '')}")
    lines.append(f"- Cycle Record ID: `{cycle_record.get('cycle_record_id', '')}`")
    lines.append(f"- Gate 4 checked at: {gate4_verdict.get('checked_at', '')}")
    lines.append(
        "| # | Check | Passed |\n|---|---|---|\n"
        + "\n".join(
            f"| {c['criterion']} | {c['description']} | {'Yes' if c['passed'] else 'No'} |"
            for c in gate4_verdict.get("checks", [])
        )
    )
    lines.append("")

    return "\n".join(lines)
