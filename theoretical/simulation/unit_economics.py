"""
Unit Economics computation and scenario generation (P1.0.4, Amendment A2).

Six independent inputs (Amendment A2 -- LTV corrected from independent
to derived, budget added as the sixth independent after founder
clarification):
    price_per_unit, variable_cost_per_unit, CAC,
    avg_customer_lifetime_months, monthly_burn, budget

Six derived metrics, recomputed from a scenario's own six (possibly
shocked) independents -- never mixed across scenarios:
    gross_margin, LTV, LTV_to_CAC, payback_period,
    runway_months, breakeven_customers

Scenario deviation: deviation_pct = uncertainty_score * STEP_CONSTANT
(10% per unit, P1.0.4c placeholder), direction per FIELD_KIND
(revenue-type favors "up"; cost-type favors "down" -- Conservative
always moves each field toward its unfavorable direction, Optimistic
toward its favorable one). uncertainty_score here uses the
CONFIRMED-inclusive mapping (Amendment A2 point 4) -- a CONFIRMED
parameter has uncertainty_score 0 and therefore zero deviation in
every scenario, with no special-cased exemption in the code; this is
the general rule reducing to a fixed point, not a separate rule.

A missing (None) independent propagates only into the derived metrics
that actually depend on it -- every other metric is still computed.
Nothing crashes on a missing value; the report surfaces it as a gap
(P1.0.4b.4).
"""

from __future__ import annotations

FIELD_KIND: dict[str, str] = {
    "price_per_unit": "revenue",
    "variable_cost_per_unit": "cost",
    "CAC": "cost",
    "avg_customer_lifetime_months": "revenue",
    "monthly_burn": "cost",
    "budget": "revenue",
}

UNCERTAINTY_BY_LABEL: dict[str, int] = {
    "CONFIRMED": 0,
    "ESTIMATE": 1,
    "ASSUMPTION": 2,
    "FOUNDER_OPINION": 2,
    "UNKNOWN": 3,
}

STEP_CONSTANT = 0.10  # P1.0.4(c) placeholder, approved 2026-07-16

INDEPENDENTS: list[str] = list(FIELD_KIND.keys())


def shocked_value(
    base_value: float | None, evidence_label: str, field_name: str, scenario: str
) -> float | None:
    """Applies the deterministic scenario deviation to one independent value."""
    if base_value is None:
        return None
    if scenario == "base":
        return base_value

    uncertainty = UNCERTAINTY_BY_LABEL[evidence_label]
    pct = uncertainty * STEP_CONSTANT
    favorable_up = FIELD_KIND[field_name] == "revenue"

    if scenario == "conservative":
        direction = -1 if favorable_up else 1
    elif scenario == "optimistic":
        direction = 1 if favorable_up else -1
    else:
        raise ValueError(f"Unknown scenario: {scenario!r}")

    return base_value * (1 + direction * pct)


def compute_unit_economics(params: dict[str, float | None]) -> dict[str, float | None]:
    """
    Pure computation, no scenario logic. `params` must contain all six
    INDEPENDENTS keys (value may be None for a missing parameter).
    Returns a dict with the six independents echoed back plus the six
    derived metrics -- any derived metric whose required inputs include
    a None independent is itself None, never a crash, never a guess.
    """
    price = params.get("price_per_unit")
    var_cost = params.get("variable_cost_per_unit")
    cac = params.get("CAC")
    lifetime = params.get("avg_customer_lifetime_months")
    burn = params.get("monthly_burn")
    budget = params.get("budget")

    contribution_margin = (
        (price - var_cost) if (price is not None and var_cost is not None) else None
    )
    gross_margin = (
        (contribution_margin / price)
        if (contribution_margin is not None and price)
        else None
    )
    ltv = (
        (contribution_margin * lifetime)
        if (contribution_margin is not None and lifetime is not None)
        else None
    )
    ltv_to_cac = (ltv / cac) if (ltv is not None and cac) else None
    payback_period = (
        (cac / contribution_margin) if (cac is not None and contribution_margin) else None
    )
    runway_months = (budget / burn) if (budget is not None and burn) else None
    breakeven_customers = (
        (burn / contribution_margin) if (burn is not None and contribution_margin) else None
    )

    return {
        "price_per_unit": price,
        "variable_cost_per_unit": var_cost,
        "CAC": cac,
        "avg_customer_lifetime_months": lifetime,
        "monthly_burn": burn,
        "budget": budget,
        "gross_margin": gross_margin,
        "LTV": ltv,
        "LTV_to_CAC": ltv_to_cac,
        "payback_period": payback_period,
        "runway_months": runway_months,
        "breakeven_customers": breakeven_customers,
    }


def compute_scenarios(approved_params: dict[str, dict]) -> dict[str, dict]:
    """
    approved_params: {field_name: {"value": float|None, "evidence_label": str}}
    for each of the six INDEPENDENTS (missing keys default to
    value=None, evidence_label="UNKNOWN").

    Returns {"base": {...}, "conservative": {...}, "optimistic": {...}},
    each a full compute_unit_economics() result computed from that
    scenario's OWN shocked independents -- scenarios never share or mix
    intermediate values.
    """
    scenarios: dict[str, dict] = {}
    for scenario in ("base", "conservative", "optimistic"):
        shocked: dict[str, float | None] = {}
        for field_name in INDEPENDENTS:
            p = approved_params.get(field_name, {"value": None, "evidence_label": "UNKNOWN"})
            shocked[field_name] = shocked_value(
                p["value"], p["evidence_label"], field_name, scenario
            )
        scenarios[scenario] = compute_unit_economics(shocked)
    return scenarios
