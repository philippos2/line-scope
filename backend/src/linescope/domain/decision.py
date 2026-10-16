"""Compose selected registered facts without inventing costs or feasibility."""


def comparison(economic, capacities, safety, maintenance, states):
    options = []
    calculated = economic["calculation"] if economic else {"options": []}
    by_option = {row["option"]: row for row in calculated["options"]}
    plans = {"REPAIR_PLAN": "REPAIR", "REPLACEMENT_PLAN": "REPLACE", "INTERIM_PLAN": "INTERIM"}
    for name in ("REPAIR", "REPLACE", "CONTINUE", "INTERIM"):
        costs = by_option.get(name)
        selected = [
            row for row in maintenance if plans.get(row["input"]["payload"]["kind"]) == name
        ]
        plan = selected[0]["calculation"] if len(selected) == 1 else None
        options.append(
            {
                "option": name,
                "feasibility": "UNKNOWN",
                "total_cost": costs["total_jpy"] if costs else None,
                "known_subtotal_jpy": costs["known_subtotal_jpy"] if costs else None,
                "duration_hours": plan["work_hours"] if plan else None,
                "downtime_hours": plan["downtime_hours"] if plan else None,
                "lead_time_hours": plan["lead_time_hours"] if plan else None,
                "interim_until": plan["interim_until"] if plan else None,
                "plan_cost_subtotal_jpy": plan["known_plan_direct_cost_subtotal_jpy"]
                if plan
                else None,
                "maintenance_input_id": selected[0]["input"]["maintenance_input_id"]
                if len(selected) == 1
                else None,
                "blocking_constraints": [],
                "residual_risk": "UNKNOWN",
                "missing_information": ["operational_feasibility", "residual_risk"]
                + ([] if costs else ["economic_input"])
                + ([] if plan or name == "CONTINUE" else ["maintenance_plan"]),
            }
        )
    focus = states[0]
    continuation = options[2]
    if focus["data"]["state_code"] in {"STOPPED", "UNDER_MAINTENANCE"}:
        continuation["blocking_constraints"].append(
            {"code": "CURRENT_EQUIPMENT_UNAVAILABLE", "evidence": focus["evidence"]}
        )
    stop = [
        row
        for row in safety
        if row["input"]["equipment_id"] == focus["equipment_id"]
        and row["calculation"]["status"] == "STOP_REQUIRED"
    ]
    for row in stop:
        continuation["blocking_constraints"].append(
            {
                "code": "HARD_SAFETY_STOP",
                "source": "REGISTERED_INPUT",
                "safety_input_id": row["input"]["safety_input_id"],
                "version": row["input"]["version"],
            }
        )
    for row in capacities:
        c, record = row["calculation"], row["input"]
        constraints = []
        state = next(value for value in states if value["equipment_id"] == record["equipment_id"])
        if state["data"]["state_code"] in {"STOPPED", "UNDER_MAINTENANCE"}:
            constraints.append(
                {"code": "CURRENT_EQUIPMENT_UNAVAILABLE", "evidence": state["evidence"]}
            )
        if c["capacity_status"] in {"INSUFFICIENT", "INCOMPATIBLE"}:
            constraints.append(
                {
                    "code": "INSUFFICIENT_CAPACITY_FOR_FULL_ABSORPTION"
                    if c["capacity_status"] == "INSUFFICIENT"
                    else "PRODUCT_INCOMPATIBLE",
                    "capacity_input_id": record["capacity_input_id"],
                }
            )
        for declaration in safety:
            if (
                declaration["input"]["equipment_id"] == record["equipment_id"]
                and declaration["calculation"]["status"] == "STOP_REQUIRED"
            ):
                constraints.append(
                    {
                        "code": "HARD_SAFETY_STOP",
                        "source": "REGISTERED_INPUT",
                        "safety_input_id": declaration["input"]["safety_input_id"],
                    }
                )
        options.append(
            {
                "option": "SUBSTITUTE",
                "equipment_id": record["equipment_id"],
                "product_id": record["product_id"],
                "capacity_input_id": record["capacity_input_id"],
                "capacity_status": c["capacity_status"],
                "required_rate": c["required_rate"],
                "available_rate": c["available_rate"],
                "shortage_rate": c["shortage_rate"],
                "quantity_unit": c["quantity_unit"],
                "recovery_status": c["recovery_status"],
                "permissible_downtime_hours": c["permissible_downtime_hours"],
                "recovery_deadline": c["recovery_deadline"],
                "total_cost": None,
                "feasibility": "UNKNOWN",
                "blocking_constraints": constraints,
                "residual_risk": "UNKNOWN",
                "missing_information": [
                    *c["missing_information"],
                    "structural_substitution",
                    "operational_safety",
                    "economic_input",
                ],
            }
        )
    for option in options:
        if option["blocking_constraints"]:
            option["feasibility"] = "INFEASIBLE"
    return {
        "source": "REGISTERED_INPUT",
        "currency": "JPY",
        "options": options,
        "excluded_options": [
            row["option"] for row in options if row["feasibility"] == "INFEASIBLE"
        ],
        "economic_preference": None,
        "decision_completeness": "PARTIAL",
        "risk": {
            key: "UNKNOWN"
            for key in ("SAFETY", "PRODUCTION", "QUALITY", "DELIVERY", "CASCADE", "ECONOMIC")
        },
        "unknowns": [
            "Selected inputs do not establish equipment-wide safety or operational feasibility",
            "Missing input is unknown; no fixture fallback",
            "Maintenance direct-cost subtotals are not added to economic totals",
            "Historical losses do not predict future failure probability",
        ],
        "calculations": [
            {
                "id": "registered_economic_options",
                "input_source": "REGISTERED_INPUT",
                "input_version": economic["input"]["version"],
                "formula": "Sum only explicitly independent registered items; see each item",
                "inputs": economic["input"],
                "result": economic["calculation"],
                "complete": all(o["total_jpy"] is not None for o in calculated["options"]),
            }
        ]
        if economic
        else [],
    }
