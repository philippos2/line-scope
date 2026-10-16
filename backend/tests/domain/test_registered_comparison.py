import pytest
from decision_fixture import records

from linescope.domain import economics, maintenance_inputs
from linescope.domain.decision import comparison


@pytest.mark.parametrize(
    "state,excluded", [("RUNNING", False), ("STOPPED", True), ("UNDER_MAINTENANCE", True)]
)
def test_registered_state_constraints_never_become_operational_permission(state, excluded):
    rows, selection = records()
    economic = {
        "input": rows["economic"]["after"],
        "calculation": economics.calculate(rows["economic"]["after"]["payload"]),
    }
    result = comparison(
        economic,
        [],
        [],
        [],
        [
            {
                "equipment_id": selection["equipment_id"],
                "data": {"state_code": state},
                "evidence": {"source": "POSTGRESQL"},
            }
        ],
    )
    assert (result["options"][2]["feasibility"] == "INFEASIBLE") is excluded
    assert result["options"][0]["total_cost"] == "1900000" and result["economic_preference"] is None
    assert not any(row["feasibility"] == "FEASIBLE" for row in result["options"])


def test_plan_subtotal_is_not_added_to_economic_total_or_used_as_a_downtime_estimate():
    rows, selection = records()
    economic = {
        "input": rows["economic"]["after"],
        "calculation": economics.calculate(rows["economic"]["after"]["payload"]),
    }
    plan = {
        "input": rows["maintenance"]["after"],
        "calculation": maintenance_inputs.calculate(
            rows["maintenance"]["after"]["payload"], selection["period_start"]
        ),
    }
    result = comparison(
        economic,
        [],
        [],
        [plan],
        [
            {
                "equipment_id": selection["equipment_id"],
                "data": {"state_code": "RUNNING"},
                "evidence": {},
            }
        ],
    )
    replacement = result["options"][1]
    assert replacement["lead_time_hours"] == "336" and replacement["downtime_hours"] == "2"
    assert replacement["total_cost"] is None and replacement["plan_cost_subtotal_jpy"] == "3000000"
