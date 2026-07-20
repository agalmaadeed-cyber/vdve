"""
Fixed, code-only translation dictionaries for the Venture Story
generator (Decision P1.0.10 point 4). Plain lookups -- no LLM, no
contextual judgment, same doctrine as this codebase's existing
DECISION_ICONS / OUTCOME_ICONS (app.py). A lookup miss falls back to
the raw technical string rather than crashing -- a translation gap is
a cosmetic issue to fix later, never a reason to fail document
generation (this module never blocks the "declared failure over
silent invention" doctrine used elsewhere in this codebase, because
there is no invented *content* here, only a missing prettification).
"""

from __future__ import annotations

EVIDENCE_LABEL_TRANSLATION: dict[str, str] = {
    "ESTIMATE": "Preliminary Estimate",
    "ASSUMPTION": "Untested Assumption",
    "FOUNDER_OPINION": "Founder's Judgment",
    "CONFIRMED": "Confirmed with Source",
    "UNKNOWN": "Not Yet Determined",
}

STRESS_OUTCOME_TRANSLATION: dict[str, str] = {
    "SURVIVES": "Held up under stress",
    "DEGRADED": "Weakened but survived",
    "BREAKS": "Failed under stress",
    "NOT_EVALUABLE": "Could not be tested (data missing)",
}

SEVERITY_TRANSLATION: dict[str, str] = {
    "LOW": "Low concern",
    "MEDIUM": "Moderate concern",
    "CRITICAL": "Critical concern",
}

KILL_STATUS_TRANSLATION: dict[str, str] = {
    "No concern": "No kill-criteria concern identified",
    "Possible match (unconfirmed)": "Possible kill-criteria match, unconfirmed at time of decision",
    "Confirmed match": "Confirmed kill-criteria match",
}

# Reader-facing lead-in for each Dossier field this generator quotes.
# Deliberately excludes founder_resources (E1-E5) -- out of scope,
# see this packet's §0(d).
FIELD_PROMPTS: dict[str, str] = {
    "A1": "The Problem",
    "A2": "Who Faces It",
    "A3": "Current Alternatives",
    "A4": "Why They Fall Short",
    "A5": "Why Now",
    "C1": "Solution Description",
    "C2": "Value Delivered",
    "C3": "What Makes It Different",
    "C4": "How Customers Use It",
    "C5": "Complexity to Build",
    "B1": "Who Pays",
    "B2": "Who Uses It",
    "B3": "Who Decides",
    "B4": "Who Benefits",
    "B5": "Target Geography",
    "B6": "Market Size",
    "B7": "Competitive Landscape",
    "D1": "Revenue Source",
    "D2": "What They're Paying For",
    "D3": "Pricing Approach",
    "D4": "Revenue Potential",
    "D5": "Initial Cost to Build",
    "D6": "Go-to-Market Channels",
    "F1": "Founder's Success Criteria",
    "F2": "Founder's Kill Criteria",
    "F3": "Known Risks",
    "F4": "Key Assumptions",
}

METRIC_LABELS: dict[str, str] = {
    "price_per_unit": "Price per Unit ($)",
    "variable_cost_per_unit": "Variable Cost per Unit ($)",
    "CAC": "Customer Acquisition Cost ($)",
    "avg_customer_lifetime_months": "Avg. Customer Lifetime (months)",
    "monthly_burn": "Monthly Burn ($)",
    "budget": "Budget ($)",
    "gross_margin": "Gross Margin (%)",
    "LTV": "Lifetime Value ($)",
    "LTV_to_CAC": "LTV : CAC Ratio",
    "payback_period": "Payback Period (months)",
    "runway_months": "Runway (months)",
    "breakeven_customers": "Breakeven Customers (#)",
}

# Display order for the financial snapshot table -- independents
# first, then derived metrics, matching Amendment A2's own split.
METRIC_ORDER: list[str] = [
    "price_per_unit", "variable_cost_per_unit", "CAC",
    "avg_customer_lifetime_months", "monthly_burn", "budget",
    "gross_margin", "LTV", "LTV_to_CAC",
    "payback_period", "runway_months", "breakeven_customers",
]
