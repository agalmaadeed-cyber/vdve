"""
Deterministic, zero-cost acceptance tests for the Unit Economics /
scenario module (P1.0.4, Amendment A2). Every value here was
hand-computed and verified by Cowork before handoff.
"""

from theoretical.simulation.unit_economics import compute_scenarios, compute_unit_economics


def _params():
    return {
        "price_per_unit": {"value": 25.0, "evidence_label": "ESTIMATE"},
        "variable_cost_per_unit": {"value": 0.02, "evidence_label": "ESTIMATE"},
        "CAC": {"value": 10.0, "evidence_label": "ASSUMPTION"},
        "avg_customer_lifetime_months": {"value": None, "evidence_label": "UNKNOWN"},
        "monthly_burn": {"value": 100.0, "evidence_label": "ESTIMATE"},
        "budget": {"value": 1000.0, "evidence_label": "CONFIRMED"},
    }


def test_base_scenario_uses_unmodified_values():
    result = compute_scenarios(_params())
    base = result["base"]
    assert base["price_per_unit"] == 25.0
    assert base["variable_cost_per_unit"] == 0.02
    assert base["CAC"] == 10.0
    assert base["monthly_burn"] == 100.0
    assert base["budget"] == 1000.0


def test_revenue_type_field_direction_price():
    result = compute_scenarios(_params())
    assert result["conservative"]["price_per_unit"] == 25.0 * 0.90  # ESTIMATE, down in conservative
    assert result["optimistic"]["price_per_unit"] == 25.0 * 1.10


def test_cost_type_field_direction_variable_cost():
    result = compute_scenarios(_params())
    assert abs(result["conservative"]["variable_cost_per_unit"] - 0.022) < 1e-9
    assert abs(result["optimistic"]["variable_cost_per_unit"] - 0.018) < 1e-9


def test_uncertainty_magnitude_scales_deviation():
    result = compute_scenarios(_params())
    # CAC is ASSUMPTION -> uncertainty=2 -> 20% swing, cost-type: up in conservative
    assert abs(result["conservative"]["CAC"] - 10 * 1.20) < 1e-9
    assert abs(result["optimistic"]["CAC"] - 10 * 0.80) < 1e-9


def test_confirmed_field_has_zero_deviation_by_general_rule():
    """Amendment A2 point 4: no special-cased exemption -- CONFIRMED
    reduces to zero deviation through the general formula alone."""
    result = compute_scenarios(_params())
    assert result["base"]["budget"] == result["conservative"]["budget"] == result["optimistic"]["budget"] == 1000.0


def test_missing_independent_propagates_only_to_dependent_metrics():
    result = compute_scenarios(_params())
    for scenario in ("base", "conservative", "optimistic"):
        assert result[scenario]["LTV"] is None
        assert result[scenario]["LTV_to_CAC"] is None
        # unaffected metrics still compute:
        assert result[scenario]["gross_margin"] is not None
        assert result[scenario]["runway_months"] is not None
        assert result[scenario]["breakeven_customers"] is not None
        assert result[scenario]["payback_period"] is not None


def test_runway_recomputed_independently_per_scenario():
    result = compute_scenarios(_params())
    assert abs(result["base"]["runway_months"] - 1000.0 / 100.0) < 1e-9
    assert abs(result["conservative"]["runway_months"] - 1000.0 / 110.0) < 1e-9  # burn shocked, budget flat (CONFIRMED)
    assert abs(result["optimistic"]["runway_months"] - 1000.0 / 90.0) < 1e-9


def test_gross_margin_formula():
    base = compute_unit_economics(
        {"price_per_unit": 25.0, "variable_cost_per_unit": 0.02, "CAC": 10.0,
         "avg_customer_lifetime_months": None, "monthly_burn": 100.0, "budget": 1000.0}
    )
    assert abs(base["gross_margin"] - (25.0 - 0.02) / 25.0) < 1e-9


def test_ltv_and_dependents_compute_when_lifetime_present():
    result = compute_unit_economics(
        {"price_per_unit": 25.0, "variable_cost_per_unit": 0.02, "CAC": 10.0,
         "avg_customer_lifetime_months": 12.0, "monthly_burn": 100.0, "budget": 1000.0}
    )
    expected_ltv = (25.0 - 0.02) * 12.0
    assert abs(result["LTV"] - expected_ltv) < 1e-9
    assert abs(result["LTV_to_CAC"] - expected_ltv / 10.0) < 1e-9


def test_completely_empty_params_never_crashes():
    result = compute_unit_economics({})
    assert all(v is None for v in result.values())


def test_metric_evidence_labels_inherit_weakest_dependency():
    from theoretical.simulation.unit_economics import compute_metric_evidence_labels

    labels = {
        "price_per_unit": "ESTIMATE",
        "variable_cost_per_unit": "ESTIMATE",
        "CAC": "ASSUMPTION",
        "avg_customer_lifetime_months": "UNKNOWN",
        "monthly_burn": "ESTIMATE",
        "budget": "CONFIRMED",
    }
    result = compute_metric_evidence_labels(labels)

    assert result["gross_margin"] == "ESTIMATE"
    assert result["LTV"] == "UNKNOWN"  # lifetime is the weakest link
    assert result["LTV_to_CAC"] == "UNKNOWN"
    assert result["payback_period"] == "ASSUMPTION"  # CAC weaker than ESTIMATE price/cost
    assert result["runway_months"] == "ESTIMATE"  # CONFIRMED budget doesn't hide ESTIMATE burn
    assert result["breakeven_customers"] == "ESTIMATE"
    # independents echoed back unchanged
    assert result["budget"] == "CONFIRMED"
    assert result["CAC"] == "ASSUMPTION"
