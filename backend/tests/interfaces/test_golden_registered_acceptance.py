"""Golden fixture uses registered facts and explicitly conditional unknowns."""

from copy import deepcopy

from decision_fixture import records
from domain.test_cost_recovery import recovery_payload
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world

from interfaces.test_controlled_action_scenarios import counts
from interfaces.test_controlled_action_scenarios import running_world as running_world
from interfaces.test_registered_decisions import auth, client
from linescope.domain import economics, maintenance_inputs, safety
from linescope.domain.canonical import canonical_json
from linescope.persistence import (
    core_capacity,
    core_economics,
    core_maintenance_inputs,
    core_safety,
)


def test_golden_registered_decision_reproduces_costs_time_capacity_safety_and_unknowns_without_writes(
    db, running_world, adapters
):
    rows, selection = records("DEGRADED")
    rows["economic"] = economics.economic_target(
        {
            "input_code": "GOLDEN-ECON",
            "equipment_id": selection["equipment_id"],
            "payload": recovery_payload(),
        }
    )
    selection["economic_input_id"] = rows["economic"]["target_id"]
    p = deepcopy(rows["safety"]["after"]["payload"])
    p["decision"] = "CONDITIONAL"
    rows["safety"] = safety.safety_target(
        {"input_code": "GOLDEN-SAFETY", "equipment_id": selection["equipment_id"], "payload": p}
    )
    selection["safety_input_ids"] = [rows["safety"]["target_id"]]
    p = deepcopy(rows["maintenance"]["after"]["payload"])
    p["direct_cost_jpy"] = "2400000"
    rows["maintenance"] = maintenance_inputs.maintenance_input_target(
        {"input_code": "GOLDEN-REPLACE", "equipment_id": selection["equipment_id"], "payload": p}
    )
    selection["maintenance_input_ids"] = [rows["maintenance"]["target_id"]]
    repair_payload = {
        **p,
        "kind": "REPAIR_PLAN",
        "lead_time_hours": "0",
        "work_hours": "8",
        "downtime_hours": "8",
        "direct_cost_jpy": "300000",
    }
    rows["repair"] = maintenance_inputs.maintenance_input_target(
        {
            "input_code": "GOLDEN-REPAIR",
            "equipment_id": selection["equipment_id"],
            "payload": repair_payload,
        }
    )
    selection["maintenance_input_ids"].append(rows["repair"]["target_id"])

    with db.transaction() as connection:
        for key, queries in (
            ("economic", core_economics),
            ("capacity", core_capacity),
            ("safety", core_safety),
            ("maintenance", core_maintenance_inputs),
            ("repair", core_maintenance_inputs),
        ):
            assert queries.write(connection, rows[key]) == 1
    before = counts(db)
    with client(db, adapters[1].driver) as api:
        response = api.post(
            "/agent",
            json={"message": "登録入力で比較 " + canonical_json(selection)},
            headers=auth(),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "partial" and "150日" in body["answer"]
    package = body["data"]["decision_package"]
    result = package["comparison"]
    repair, replacement, continuation, interim, substitute = result["options"]
    assert (
        repair["total_cost"] == "1900000"
        and replacement["total_cost"] == "2400000"
        and continuation["total_cost"] == "480000"
    )
    assert repair["duration_hours"] == "8" and repair["downtime_hours"] == "8"
    assert result["simple_cost_recovery"]["days"] == "150"
    assert result["economics"]["loss_per_hour"] == "200000"
    assert replacement["lead_time_hours"] == "336" and replacement["downtime_hours"] == "2"
    assert (
        continuation["safety_basis"]["status"] == "CONDITIONAL"
        and continuation["feasibility"] == "UNKNOWN"
    )
    assert (
        substitute["structural_basis"]["status"] == "AVAILABLE"
        and substitute["shortage_rate"] == "30"
    )
    assert substitute["permissible_downtime_hours"] == "4" and substitute[
        "recovery_deadline"
    ].startswith("2026-10-01T04:00:00")
    assert {row["entity_type"] for row in package["impact"]["reached_nodes"]} >= {
        "Product",
        "Process",
        "ProductionOperation",
    }
    assert set(result["risk_details"]) == {
        "SAFETY",
        "PRODUCTION",
        "QUALITY",
        "DELIVERY",
        "CASCADE",
        "ECONOMIC",
    }
    assert all(
        row["operational_permission"] is False
        for row in (continuation["safety_basis"], substitute["condition_assessment"])
    )
    assert (
        body["evidence"]["impact"]["graph_generation"]
        == body["evidence"]["alternatives"]["graph_generation"]
    )
    assert package["automatic_state_change"] is False and counts(db) == before
