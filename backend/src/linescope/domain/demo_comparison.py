"""Deterministic prototype arithmetic over declared demo inputs only.

These exact-integer fixture formulas do not establish production money, calendar,
capacity, rounding, authority or safety rules (PO-B01..07 remain undecided).
"""

from copy import deepcopy

FIXTURES = {
    "STOPPED": {
        "source": "MOCK_FIXTURE",
        "fixture_version": "decision-inputs:v2:BS-02-06",
        "analysis_condition": "HYPOTHETICAL_STOP",
        "currency": "JPY",
        "product_loss_per_hour": {"P-100": 120000, "P-200": 80000},
        "independent_addition": True,
        "repair_cost": 300000,
        "repair_hours": 8,
        "replacement_cost": 3000000,
        "replacement_lead_days": 14,
        "required_capacity": 90,
        "available_capacity": 60,
        "degradation_loss_per_hour": None,
        "operating_hours_per_day": None,
        "days_until_update": None,
        "hard_safety_stop": None,
    },
    "DEGRADED": {
        "source": "MOCK_FIXTURE",
        "fixture_version": "decision-inputs:v2:BS-03",
        "analysis_condition": "HYPOTHETICAL_DEGRADATION",
        "currency": "JPY",
        "product_loss_per_hour": {},
        "independent_addition": None,
        "repair_cost": None,
        "repair_hours": None,
        "replacement_cost": 2400000,
        "replacement_lead_days": None,
        "required_capacity": None,
        "available_capacity": None,
        "degradation_loss_per_hour": 1000,
        "operating_hours_per_day": 16,
        "days_until_update": 30,
        "hard_safety_stop": None,
    },
}


def fixture(name):
    return deepcopy(FIXTURES[name])


def compare(inputs):
    """Keep UNKNOWN distinct from zero; no floating point or invented period."""
    inputs = deepcopy(inputs)
    if inputs["source"] != "MOCK_FIXTURE" or inputs["currency"] != "JPY":
        raise ValueError("Prototype arithmetic accepts declared JPY demo fixtures only")
    rates = inputs["product_loss_per_hour"]
    numbers = [
        *rates.values(),
        *[
            inputs[key]
            for key in (
                "repair_cost",
                "repair_hours",
                "replacement_cost",
                "replacement_lead_days",
                "required_capacity",
                "available_capacity",
                "degradation_loss_per_hour",
                "operating_hours_per_day",
                "days_until_update",
            )
        ],
    ]
    if any(value is not None and (type(value) is not int or value < 0) for value in numbers):
        raise ValueError("Demo arithmetic requires nonnegative exact integers or unknown")
    for key in ("independent_addition", "hard_safety_stop"):
        if inputs[key] is not None and type(inputs[key]) is not bool:
            raise ValueError("Invalid demo condition")
    calculations = []

    def calculation(name, values, formula, result, unit):
        calculations.append(
            {
                "id": name,
                "source": "DETERMINISTIC_DEMO_CALCULATION",
                "input_source": inputs["source"],
                "input_version": inputs["fixture_version"],
                "inputs": values,
                "formula": formula,
                "result": result,
                "unit": unit,
                "complete": result is not None,
            }
        )
        return result

    known = {key: value for key, value in rates.items() if value is not None}
    additive = inputs["independent_addition"] is True
    subtotal = sum(known.values()) if additive and known else None
    total = subtotal if rates and len(known) == len(rates) else None
    calculation(
        "loss_rate", rates, "sum(independently_additive_product_loss_rates)", total, "JPY/hour"
    )
    cost, hours = inputs["repair_cost"], inputs["repair_hours"]
    downtime = calculation(
        "repair_downtime",
        {"loss_per_hour": total, "hours": hours},
        "loss_per_hour * hours",
        total * hours if total is not None and hours is not None else None,
        "JPY",
    )
    repair_total = calculation(
        "repair_total",
        {"downtime_loss": downtime, "direct_cost": cost},
        "downtime_loss + direct_cost",
        downtime + cost if downtime is not None and cost is not None else None,
        "JPY",
    )
    required, available = inputs["required_capacity"], inputs["available_capacity"]
    shortage = calculation(
        "capacity_shortage",
        {"required": required, "available": available},
        "max(required - available, 0)",
        max(required - available, 0) if required is not None and available is not None else None,
        "units/hour",
    )
    loss, daily_hours, days = (
        inputs["degradation_loss_per_hour"],
        inputs["operating_hours_per_day"],
        inputs["days_until_update"],
    )
    daily = loss * daily_hours if loss is not None and daily_hours is not None else None
    cumulative = calculation(
        "degradation_loss",
        {"loss_per_operating_hour": loss, "operating_hours_per_day": daily_hours, "days": days},
        "loss_per_operating_hour * operating_hours_per_day * days",
        daily * days if daily is not None and days is not None else None,
        "JPY",
    )
    replacement = inputs["replacement_cost"]
    recovery = None
    if daily is not None and daily > 0 and replacement is not None:
        recovery = {"numerator": replacement, "denominator": daily, "unit": "days"}
        if replacement % daily == 0:
            recovery = replacement // daily
    calculation(
        "simple_cost_recovery",
        {"replacement_cost": replacement, "degradation_loss_per_day": daily},
        "replacement_cost / degradation_loss_per_day",
        recovery,
        "days",
    )
    options = [
        {
            "option": "REPAIR",
            "feasibility": "UNKNOWN",
            "direct_cost": cost,
            "duration_hours": hours,
            "production_loss": downtime,
            "total_cost": repair_total,
            "formula": "loss_per_hour * hours + direct_cost",
        },
        {
            "option": "REPLACE",
            "feasibility": "UNKNOWN",
            "direct_cost": replacement,
            "lead_time_days": inputs["replacement_lead_days"],
            "duration_hours": None,
            "production_loss": None,
            "total_cost": None,
        },
        {
            "option": "SUBSTITUTE",
            "feasibility": "UNKNOWN",
            "equipment_code": "M-208",
            "required_units_per_hour": required,
            "available_units_per_hour": available,
            "shortage_units_per_hour": shortage,
            "capacity_result": "UNKNOWN"
            if shortage is None
            else "SHORTAGE"
            if shortage > 0
            else "SUFFICIENT_IN_FIXTURE",
            "formula": "max(required - available, 0)",
        },
        {
            "option": "CONTINUE",
            "feasibility": "INFEASIBLE" if inputs["hard_safety_stop"] is True else "UNKNOWN",
            "safety_permission": "UNKNOWN",
            "cumulative_degradation_loss": cumulative,
            "days_until_update": days,
            "reason": "MOCK_HARD_SAFETY_CONSTRAINT"
            if inputs["hard_safety_stop"] is True
            else "SAFETY_NOT_DETERMINED",
        },
    ]
    return {
        "source": inputs["source"],
        "fixture_version": inputs["fixture_version"],
        "analysis_condition": inputs["analysis_condition"],
        "inputs": inputs,
        "economics": {
            "currency": inputs["currency"],
            "product_loss_per_hour": rates,
            "independent_addition": inputs["independent_addition"],
            "loss_per_hour": total,
            "known_subtotal_per_hour": subtotal,
            "complete": total is not None,
            "missing_products": sorted(set(rates) - set(known)),
        },
        "options": options,
        "calculations": calculations,
        "economic_preference": None,
        "risk": {
            key: "UNKNOWN"
            for key in ("SAFETY", "PRODUCTION", "QUALITY", "DELIVERY", "CASCADE", "ECONOMIC")
        },
        "unknowns": [
            "Costs, capacity and safety inputs are demo fixtures, not business facts",
            "Common comparison period and operational safety are not determined",
            "Replacement lead time is not downtime; replacement total is unknown",
        ],
    }
