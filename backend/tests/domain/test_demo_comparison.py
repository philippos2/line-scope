import pytest

from linescope.domain.demo_comparison import compare, fixture


def test_repair_costs_are_derived_from_inputs_and_formulas():
    inputs = fixture("STOPPED")
    result = compare(inputs)
    assert result["economics"]["loss_per_hour"] == 200000
    assert result["options"][0]["production_loss"] == 1600000
    assert result["options"][0]["total_cost"] == 1900000
    inputs["repair_hours"] = 9
    assert compare(inputs)["options"][0]["total_cost"] == 2100000
    assert result["calculations"][2]["inputs"] == {"downtime_loss": 1600000, "direct_cost": 300000}
    assert result["options"][1]["total_cost"] is None
    assert result["economic_preference"] is None


def test_degradation_fixture_has_cumulative_loss_and_simple_recovery():
    result = compare(fixture("DEGRADED"))
    values = {item["id"]: item["result"] for item in result["calculations"]}
    assert values["degradation_loss"] == 480000
    assert values["simple_cost_recovery"] == 150
    assert result["options"][3]["feasibility"] == "UNKNOWN"


def test_missing_product_loss_is_not_zero_or_a_complete_total():
    inputs = fixture("STOPPED")
    inputs["product_loss_per_hour"]["P-200"] = None
    result = compare(inputs)
    assert result["economics"]["known_subtotal_per_hour"] == 120000
    assert result["economics"]["loss_per_hour"] is None
    assert result["economics"]["missing_products"] == ["P-200"]
    assert result["options"][0]["total_cost"] is None


def test_nonadditive_losses_cannot_be_summed():
    inputs = fixture("STOPPED")
    inputs["independent_addition"] = False
    assert compare(inputs)["economics"]["known_subtotal_per_hour"] is None


def test_missing_repair_cost_prevents_total():
    inputs = fixture("STOPPED")
    inputs["repair_cost"] = None
    result = compare(inputs)
    assert result["options"][0]["production_loss"] == 1600000
    assert result["options"][0]["total_cost"] is None


@pytest.mark.parametrize("required,available,shortage", [(90, 60, 30), (60, 80, 0)])
def test_capacity_result_does_not_grant_operational_feasibility(required, available, shortage):
    inputs = fixture("STOPPED")
    inputs.update(required_capacity=required, available_capacity=available)
    result = compare(inputs)["options"][2]
    assert result["shortage_units_per_hour"] == shortage
    assert result["feasibility"] == "UNKNOWN"


def test_unknown_capacity_is_not_zero_shortage():
    inputs = fixture("STOPPED")
    inputs["available_capacity"] = None
    assert compare(inputs)["options"][2]["shortage_units_per_hour"] is None


def test_mock_safety_constraint_excludes_even_low_cost_continuation():
    inputs = fixture("DEGRADED")
    inputs["hard_safety_stop"] = True
    assert compare(inputs)["options"][3]["feasibility"] == "INFEASIBLE"


@pytest.mark.parametrize("invalid", [1.5, True, -1])
def test_demo_inputs_require_exact_nonnegative_integers(invalid):
    inputs = fixture("STOPPED")
    inputs["repair_cost"] = invalid
    with pytest.raises(ValueError):
        compare(inputs)
