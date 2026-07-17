"""
Fixed stress-test library (P1.0.5), quantitative_shock type only.

Six tests, each shocking exactly one of the six INDEPENDENTS
(theoretical.simulation.unit_economics) and reading one derived
metric. break_threshold and degraded_ceiling are placeholders --
same status as the section-weight table (P1.0.3b) and the scenario
step constant (P1.0.4c): reasoned defaults, explicitly flagged for
founder calibration against real usage, not a guess presented as
final.

Every test is executed by theoretical.stress_tests.engine.run_quantitative_shock
against a founder-approved parameter set (never raw/unreviewed
extraction output -- same governance as Packet #4's scenario
computation, P1.0.4c.2).
"""

from __future__ import annotations

FIXED_TESTS: list[dict] = [
    {
        "test_id": "ST-01",
        "category": "cost",
        "description": "CAC doubles (acquisition channel gets more expensive or less efficient).",
        "shocked_param": "CAC",
        "shock_multiplier": 2.0,
        "affected_metric": "LTV_to_CAC",
        "break_threshold": 1.0,      # below 1.0, each customer costs more than they return
        "degraded_ceiling": 3.0,     # commonly-cited "healthy" LTV:CAC floor
    },
    {
        "test_id": "ST-02",
        "category": "demand",
        "description": "Customer lifetime halves (churn doubles).",
        "shocked_param": "avg_customer_lifetime_months",
        "shock_multiplier": 0.5,
        "affected_metric": "LTV_to_CAC",
        "break_threshold": 1.0,
        "degraded_ceiling": 3.0,
    },
    {
        "test_id": "ST-03",
        "category": "founder",
        "description": "Available budget halves (funding shortfall or delay).",
        "shocked_param": "budget",
        "shock_multiplier": 0.5,
        "affected_metric": "runway_months",
        "break_threshold": 3.0,      # under 3 months runway is existential
        "degraded_ceiling": 6.0,
    },
    {
        "test_id": "ST-04",
        "category": "pricing",
        "description": "Price drops 20% (competitive pressure or forced discount).",
        "shocked_param": "price_per_unit",
        "shock_multiplier": 0.8,
        "affected_metric": "gross_margin",
        "break_threshold": 0.0,      # negative or zero margin is unsustainable
        "degraded_ceiling": 0.15,
    },
    {
        "test_id": "ST-05",
        "category": "cost",
        "description": "Variable cost per unit rises 30% (supplier/API cost shock).",
        "shocked_param": "variable_cost_per_unit",
        "shock_multiplier": 1.3,
        "affected_metric": "gross_margin",
        "break_threshold": 0.0,
        "degraded_ceiling": 0.15,
    },
    {
        "test_id": "ST-06",
        "category": "founder",
        "description": "Monthly burn rises 50% (overspend / underestimated cost).",
        "shocked_param": "monthly_burn",
        "shock_multiplier": 1.5,
        "affected_metric": "runway_months",
        "break_threshold": 3.0,
        "degraded_ceiling": 6.0,
    },
]

# P1.0.5's fixed taxonomy -- generated tests (engine.generate_test_specs)
# classify into these same six categories, so overlap with the fixed
# library is a simple category match, never hidden (P1.0.5 governance).
CATEGORIES: tuple[str, ...] = (
    "demand", "pricing", "cost", "competition", "regulation", "founder",
)

# Design gap (c) closed in this packet's header (§0) -- Dossier section
# letter to P1.0.5 category, used only for generated tests (fixed tests
# above declare their category directly).
SECTION_TO_CATEGORY: dict[str, str] = {
    "A": "demand",
    "B": "demand",
    "C": "competition",
    "D": "pricing",
    "E": "founder",
    "F": "regulation",
}
