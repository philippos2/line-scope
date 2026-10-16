"""Explicit registered fixtures in disposable PG; never a runtime provider."""

from domain.test_capacity import payload as capacity_payload
from domain.test_economics import payload as economic_payload
from domain.test_maintenance_inputs import payload as maintenance_payload
from domain.test_safety import payload as safety_payload

from linescope.demo_graph_seed import demo_id
from linescope.demo_seed import DEMO_EQUIPMENT
from linescope.domain import capacity, economics, maintenance_inputs, safety
from linescope.persistence import (
    core_capacity,
    core_economics,
    core_maintenance_inputs,
    core_safety,
)


def records(scenario="STOPPED"):
    focus, alternative = (str(row[0]) for row in DEMO_EQUIPMENT)
    ep, cp, sp, mp = economic_payload(), capacity_payload(), safety_payload(), maintenance_payload()
    if scenario in {"DEGRADED", "SAFETY_STOP"}:
        ep["period_end"] = "2026-10-31T00:00:00Z"
        ep["operating_hours"] = "480"
        ep["options"][2]["items"][0].update(amount="1000", hours="480")
        for option in ep["options"]:
            for item in option["items"]:
                item["valid_to"] = ep["period_end"]
    if scenario == "MISSING_LOSS":
        ep["options"][0]["items"][2]["amount"] = None
    if scenario == "MISSING_REPAIR_COST":
        ep["options"][0]["items"][0]["amount"] = None
    if scenario == "NONADDITIVE_LOSS":
        ep["options"][0]["items"][1]["independent"] = False
    if scenario == "SUFFICIENT_CAPACITY":
        cp["normal_rate"] = "130"
    cp.update(period_start=ep["period_start"], period_end=ep["period_end"])
    sp["decision"] = "STOP_REQUIRED" if scenario == "SAFETY_STOP" else "UNKNOWN"
    mp.update(
        kind="REPLACEMENT_PLAN",
        period_start=ep["period_start"],
        period_end=ep["period_end"],
        direct_cost_jpy="3000000",
        include_replacement_cost=False,
        replacement_cost_jpy=None,
    )
    rows = {
        "economic": economics.economic_target(
            {"input_code": "DECISION-ECON", "equipment_id": focus, "payload": ep}
        ),
        "capacity": capacity.capacity_target(
            {
                "input_code": "DECISION-CAP",
                "equipment_id": alternative,
                "product_id": str(demo_id("P-100")),
                "payload": cp,
            }
        ),
        "safety": safety.safety_target(
            {"input_code": "DECISION-SAFE", "equipment_id": focus, "payload": sp}
        ),
        "maintenance": maintenance_inputs.maintenance_input_target(
            {"input_code": "DECISION-PLAN", "equipment_id": focus, "payload": mp}
        ),
    }
    selection = {
        "equipment_id": focus,
        "period_start": ep["period_start"],
        "period_end": ep["period_end"],
        "economic_input_id": rows["economic"]["target_id"],
        "capacity_input_ids": [rows["capacity"]["target_id"]],
        "safety_input_ids": [rows["safety"]["target_id"]],
        "maintenance_input_ids": [rows["maintenance"]["target_id"]],
    }
    return rows, selection


def seed_registered(db, scenario="STOPPED"):
    rows, selection = records(scenario)
    with db.transaction() as connection:
        for key, queries in (
            ("economic", core_economics),
            ("capacity", core_capacity),
            ("safety", core_safety),
            ("maintenance", core_maintenance_inputs),
        ):
            assert queries.write(connection, rows[key]) == 1
    return selection
