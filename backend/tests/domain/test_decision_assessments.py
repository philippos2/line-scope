from copy import deepcopy

import pytest
from decision_fixture import records

from domain.test_maintenance_inputs import payload as maintenance_payload
from linescope.domain import capacity, economics, maintenance_inputs, safety
from linescope.domain.decision import comparison
from linescope.domain.decision_assessments import (
    assess,
    economic_breakdown,
    safety_basis,
    structural_basis,
)


def inputs():
    rows, selection = records()
    services = {
        "economic": economics,
        "capacity": capacity,
        "safety": safety,
        "maintenance": maintenance_inputs,
    }
    result = {}
    for key, target in rows.items():
        record = target["after"]
        result[key] = {
            "input": record,
            "calculation": services[key].calculate(record["payload"], selection["period_start"])
            if key in {"safety", "maintenance"}
            else services[key].calculate(record["payload"]),
        }
    states = [
        {"equipment_id": identifier, "data": {"state_code": "RUNNING"}, "evidence": {}}
        for identifier in (selection["equipment_id"], result["capacity"]["input"]["equipment_id"])
    ]
    return result, states


@pytest.mark.parametrize(
    "decisions,expected",
    [
        ([], "UNKNOWN"),
        (["CONDITIONAL"], "CONDITIONAL"),
        (["UNKNOWN"], "UNKNOWN"),
        (["CONDITIONAL", "UNKNOWN"], "UNKNOWN"),
        (["CONDITIONAL", "STOP_REQUIRED"], "STOP_REQUIRED"),
    ],
)
def test_selected_safety_basis_does_not_certify_unselected_scope(decisions, expected):
    rows, states = inputs()
    selected = []
    for decision in decisions:
        row = deepcopy(rows["safety"])
        row["input"]["payload"]["decision"] = decision
        row["calculation"] = safety.calculate(row["input"]["payload"], "2026-10-01T00:00:00Z")
        selected.append(row)
    basis = safety_basis(selected, states[0]["equipment_id"])
    assert basis["status"] == expected and basis["operational_permission"] is False
    assert "equipment_wide_safety" in basis["unknowns"]


@pytest.mark.parametrize(
    "condition,expected",
    [("INCOMPLETE", "UNKNOWN"), ("ABSENT", "NOT_REGISTERED"), ("UNAVAILABLE", "UNAVAILABLE")],
)
def test_structure_never_fills_unknown_or_invents_a_substitute(condition, expected):
    rows, states = inputs()
    focus, other = (row["equipment_id"] for row in states)
    data = {
        "complete": condition != "INCOMPLETE",
        "alternatives": [
            {"excluded_node": {"entity_type": "Equipment", "entity_id": focus}, "candidates": []}
        ],
    }
    if condition == "UNAVAILABLE":
        data["alternatives"][0]["candidates"].append(
            {
                "candidate": {"entity_type": "Equipment", "entity_id": other},
                "availability": "UNAVAILABLE",
                "reason": "CURRENT_STATE",
            }
        )
    assert structural_basis(data, other, focus)["status"] == expected


@pytest.mark.parametrize(
    "scenario,total,subtotal",
    [
        ("STOPPED", "200000", "200000"),
        ("MISSING_LOSS", None, "120000"),
        ("NONADDITIVE_LOSS", None, "80000"),
    ],
)
def test_registered_rates_keep_missing_and_nonindependent_loss_separate(scenario, total, subtotal):
    rows, _ = records(scenario)
    result = economic_breakdown({"input": rows["economic"]["after"]})
    assert result["loss_per_hour"] == total and result["known_subtotal_per_hour"] == subtotal
    assert result["complete"] is (total is not None)
    assert result["scope"] == "SELECTED_REPAIR_STOPPAGE_ITEMS" and result["version"] == 1


def enriched(rows, states):
    impact = {"complete": True, "limit_reason": None, "representative_paths": []}
    profile = comparison(
        rows["economic"], [rows["capacity"]], [rows["safety"]], [rows["maintenance"]], states
    )
    return assess(
        profile,
        rows["economic"],
        [rows["capacity"]],
        [rows["safety"]],
        [rows["maintenance"]],
        states,
        impact,
        None,
    )


def test_known_cost_pair_is_not_an_execution_recommendation():
    rows, states = inputs()
    result = enriched(rows, states)
    pairs = result["cost_comparison"]["pairs"]
    assert len(pairs) == 1 and pairs[0]["lower_cost"] == "CONTINUE"
    assert pairs[0]["left_minus_right_jpy"] == "1883998.000"
    assert (
        result["economic_preference"] is None
        and result["cost_comparison"]["recommendation"] is None
    )
    assert "REPLACE" in result["cost_comparison"]["unpriced_options"]
    assert result["decision_completeness"] == "PARTIAL"


def test_historical_loss_is_displayed_without_changing_future_cost():
    rows, states = inputs()
    p = maintenance_payload()
    p.update(
        kind="FAILURE_RECORD",
        period_end="2021-01-01T00:00:00Z",
        lead_time_hours=None,
        replacement_cost_jpy=None,
        include_replacement_cost=None,
        past_loss_jpy="120000",
    )
    record = maintenance_inputs.maintenance_input_target(
        {"input_code": "HISTORY", "equipment_id": states[0]["equipment_id"], "payload": p}
    )["after"]
    rows["maintenance"] = {
        "input": record,
        "calculation": maintenance_inputs.calculate(p, "2026-10-01T00:00:00Z"),
    }
    result = enriched(rows, states)
    assert result["history"][0]["calculation"]["past_loss_jpy"] == "120000"
    assert result["history"][0]["included_in_future_cost"] is False
    assert result["history"][0]["calculation"]["future_failure_probability"] is None
    assert result["options"][0]["total_cost"] == "1900000"


def test_distinct_loss_hours_do_not_create_a_simultaneous_hourly_rate():
    rows, _ = records()
    record = rows["economic"]["after"]
    stoppage = next(row for row in record["payload"]["options"] if row["option"] == "REPAIR")[
        "items"
    ]
    next(row for row in stoppage if row["key"] == "P200")["hours"] = "4"
    result = economic_breakdown({"input": record})
    assert result["loss_per_hour"] is None and result["known_subtotal_per_hour"] is None
    assert result["complete"] is False and len(result["items"]) == 2
