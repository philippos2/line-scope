"""Conditional simple cost recovery from explicit registered assumptions."""

from decimal import ROUND_CEILING, Decimal, localcontext

from .input_values import exact, quantity, text


def normalize(value, *, operating_hours, period_micros):
    if value is None:
        return None
    exact(
        value,
        {
            "daily_operating_hours",
            "constant_daily_operation",
            "replacement_removes_degradation",
            "source",
            "certainty",
        },
    )
    hours = quantity(value["daily_operating_hours"], nullable=True)
    if hours is not None and Decimal(hours) > 24:
        raise ValueError("Daily operating hours exceed 24")
    for key in ("constant_daily_operation", "replacement_removes_degradation"):
        if value[key] is not None and type(value[key]) is not bool:
            raise ValueError("Explicit assumption or unknown required")
    if value["certainty"] not in ("ESTIMATED", "CONFIRMED"):
        raise ValueError("Invalid recovery certainty")
    if value["constant_daily_operation"] is True and hours is not None:
        with localcontext() as context:
            context.prec = 64
            if Decimal(hours) * period_micros != Decimal(operating_hours) * 86400000000:
                raise ValueError(
                    "Constant daily operation must match explicit period operating hours"
                )
    return {**value, "daily_operating_hours": hours, "source": text(value["source"])}


def calculate(payload):
    assumptions = payload.get("cost_recovery")
    result = {
        "status": "UNKNOWN",
        "days": None,
        "unit": "days",
        "rounding": "CEILING_6_DECIMALS",
        "formula": "registered replacement direct costs / (registered degradation loss per operating hour * daily operating hours)",
        "assumptions": assumptions,
        "inputs": {},
        "missing_information": [],
        "is_breakeven": False,
        "recommendation": None,
    }
    if assumptions is None:
        result["missing_information"] = ["registered_cost_recovery_assumptions"]
        return result
    missing = result["missing_information"]
    for key in ("constant_daily_operation", "replacement_removes_degradation"):
        if assumptions[key] is not True:
            missing.append(key)
    daily = assumptions["daily_operating_hours"]
    if daily is None or Decimal(daily) <= 0:
        missing.append("positive_daily_operating_hours")
    options = {row["option"]: row for row in payload["options"]}
    costs = [item for item in options["REPLACE"]["items"] if item["kind"] == "DIRECT"]
    losses = [item for item in options["CONTINUE"]["items"] if item["kind"] == "DEGRADATION"]
    if any(item["hours"] != payload["operating_hours"] for item in losses):
        missing.append("degradation_applies_to_all_operating_hours")
    for name, items in (("replacement_direct_costs", costs), ("degradation_loss_rates", losses)):
        if not items or any(item["amount"] is None or not item["independent"] for item in items):
            missing.append(name)
    # A complete option attests the declared scope; absent cost/loss scope is not free.
    for name in ("REPLACE", "CONTINUE"):
        if not options[name]["complete"]:
            missing.append(name.lower() + "_scope_completeness")
    result["inputs"] = {
        "replacement_items": costs,
        "degradation_items": losses,
        "daily_operating_hours": daily,
    }
    if missing:
        return result
    with localcontext() as context:
        context.prec = 64
        investment = sum((Decimal(item["amount"]) for item in costs), Decimal(0))
        hourly = sum((Decimal(item["amount"]) for item in losses), Decimal(0))
        result["inputs"].update(
            replacement_direct_cost_jpy=format(investment, "f"),
            degradation_loss_per_hour_jpy=format(hourly, "f"),
        )
        if hourly == 0:
            result["status"] = "NO_RECOVERY_FROM_DECLARED_LOSS"
            return result
        days = (investment / (hourly * Decimal(daily))).quantize(
            Decimal("0.000001"), rounding=ROUND_CEILING
        )
        result.update(status="CONDITIONAL", days=format(days, "f").rstrip("0").rstrip("."))
    return result
