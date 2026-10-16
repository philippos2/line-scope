"""Explain selected facts; costs and conditional declarations are not permissions."""

from decimal import Decimal, localcontext
from itertools import combinations


def safety_basis(rows, equipment_id):
    selected = [row for row in rows if row["input"]["equipment_id"] == equipment_id]
    statuses = [row["calculation"]["status"] for row in selected]
    status = (
        "STOP_REQUIRED"
        if "STOP_REQUIRED" in statuses
        else "CONDITIONAL"
        if statuses and all(value == "CONDITIONAL" for value in statuses)
        else "UNKNOWN"
    )
    return {
        "status": status,
        "scope": "SELECTED_INPUTS_ONLY",
        "operational_permission": False,
        "declarations": [
            {"input": row["input"], "assessment": row["calculation"]} for row in selected
        ],
        "unknowns": ["equipment_wide_safety", "quality", "future_failure_probability"],
    }


def structural_basis(alternatives, equipment_id, focus_id):
    if alternatives is None or not alternatives["complete"]:
        return {"status": "UNKNOWN", "reason": "INCOMPLETE_OR_UNAVAILABLE_ANALYSIS"}
    group = next(
        (
            row
            for row in alternatives["alternatives"]
            if row["excluded_node"] == {"entity_type": "Equipment", "entity_id": focus_id}
        ),
        None,
    )
    candidate = (
        next(
            (
                row
                for row in group["candidates"]
                if row["candidate"] == {"entity_type": "Equipment", "entity_id": equipment_id}
            ),
            None,
        )
        if group
        else None
    )
    if candidate is None:
        return {"status": "NOT_REGISTERED", "reason": "NO_REGISTERED_ONE_STEP_SUBSTITUTION"}
    return {
        "status": candidate["availability"],
        "candidate": candidate,
        "reason": candidate["reason"],
        "scope": "STRUCTURAL_CANDIDATE_ONLY",
    }


def economic_breakdown(economic):
    if economic is None:
        return {
            "currency": "JPY",
            "loss_per_hour": None,
            "known_subtotal_per_hour": None,
            "complete": False,
        }
    repair = next(
        row for row in economic["input"]["payload"]["options"] if row["option"] == "REPAIR"
    )
    items = [row for row in repair["items"] if row["kind"] == "STOPPAGE"]
    known = [row for row in items if row["amount"] is not None and row["independent"]]
    common_hours = (
        bool(items) and len({row["hours"] for row in items}) == 1 and items[0]["hours"] is not None
    )
    complete = (
        bool(items)
        and len(known) == len(items)
        and len({row["hours"] for row in items}) == 1
        and items[0]["hours"] is not None
    )
    with localcontext() as context:
        context.prec = 64
        subtotal = format(sum((Decimal(row["amount"]) for row in known), Decimal(0)), "f")
    return {
        "currency": "JPY",
        "scope": "SELECTED_REPAIR_STOPPAGE_ITEMS",
        "loss_per_hour": subtotal if complete else None,
        "known_subtotal_per_hour": subtotal if common_hours else None,
        "complete": complete,
        "economic_input_id": economic["input"]["economic_input_id"],
        "version": economic["input"]["version"],
        "items": items,
        "assumptions": ["Registered independent scopes only; not a factory-wide loss rate"],
    }


def cost_pairs(options):
    pairs = []
    with localcontext() as context:
        context.prec = 64
        for left, right in combinations(options, 2):
            if left["total_cost"] is None or right["total_cost"] is None:
                continue
            difference = Decimal(left["total_cost"]) - Decimal(right["total_cost"])
            pairs.append(
                {
                    "left": left["option"],
                    "right": right["option"],
                    "left_minus_right_jpy": format(difference, "f"),
                    "lower_cost": left["option"]
                    if difference < 0
                    else right["option"]
                    if difference > 0
                    else "TIE",
                    "excluded_from_execution": [
                        row["option"] for row in (left, right) if row["feasibility"] == "INFEASIBLE"
                    ],
                }
            )
    return {
        "scope": "KNOWN_TOTALS_WITHIN_SELECTED_ECONOMIC_INPUT",
        "recommendation": None,
        "pairs": pairs,
        "unpriced_options": [row["option"] for row in options if row["total_cost"] is None],
    }


def assess(profile, economic, capacities, safety, maintenance, states, impact, alternatives):
    focus_id = states[0]["equipment_id"]
    for option in profile["options"]:
        equipment_id = option.get("equipment_id", focus_id)
        basis = safety_basis(safety, equipment_id)
        option["safety_basis"] = basis
        if option["option"] in {"CONTINUE", "SUBSTITUTE"}:
            option["missing_information"] = [
                key for key in option["missing_information"] if key != "operational_safety"
            ]
            if basis["status"] != "CONDITIONAL":
                option["missing_information"].append("confirmed_continued_operation_conditions")
        if option["option"] != "SUBSTITUTE":
            continue
        structure = structural_basis(alternatives, equipment_id, focus_id)
        option["structural_basis"] = structure
        if structure["status"] in {"NOT_REGISTERED", "UNAVAILABLE"}:
            option["blocking_constraints"].append(
                {"code": "STRUCTURAL_SUBSTITUTION_UNAVAILABLE", "basis": structure}
            )
            option["feasibility"] = "INFEASIBLE"
        if structure["status"] == "AVAILABLE":
            option["missing_information"].remove("structural_substitution")
        # Quality and actual permission remain unknown even when the declared gates agree.
        option["condition_assessment"] = {
            "structure": structure["status"],
            "capacity": option["capacity_status"],
            "safety": basis["status"],
            "quality": "UNKNOWN",
            "operational_permission": False,
        }
    profile["excluded_options"] = [
        row["option"] for row in profile["options"] if row["feasibility"] == "INFEASIBLE"
    ]
    profile["economics"] = economic_breakdown(economic)
    profile["cost_comparison"] = cost_pairs(profile["options"])
    profile["history"] = [
        {"input": row["input"], "calculation": row["calculation"], "included_in_future_cost": False}
        for row in maintenance
        if row["input"]["payload"]["kind"].endswith("_RECORD")
    ]
    profile["risk_details"] = {
        "SAFETY": {
            "facts": [
                row["safety_basis"] for row in profile["options"] if row["option"] == "CONTINUE"
            ],
            "unknowns": ["equipment_wide_safety", "future_failure_probability"],
        },
        "PRODUCTION": {
            "facts": [
                {"input": row["input"], "calculation": row["calculation"]} for row in capacities
            ],
            "unknowns": ["actual_production_impact", "quality"],
        },
        "QUALITY": {"facts": [], "unknowns": ["quality_acceptance_basis"]},
        "DELIVERY": {
            "facts": [
                {
                    "capacity_input_id": row["input"]["capacity_input_id"],
                    "recovery": row["input"]["payload"]["recovery"],
                    "calculation": row["calculation"],
                }
                for row in capacities
                if row["calculation"]["recovery_status"] == "CONDITIONAL"
            ],
            "unknowns": ["general_delivery_guarantee"],
        },
        "CASCADE": {
            "facts": [
                {
                    "complete": impact["complete"],
                    "limit_reason": impact["limit_reason"],
                    "representative_paths": impact["representative_paths"],
                }
            ],
            "unknowns": ["actual_cascade_failure"],
        },
        "ECONOMIC": {
            "facts": [profile["economics"], profile["cost_comparison"]],
            "unknowns": ["unregistered_costs", "future_failure_probability"],
        },
    }
    return profile
