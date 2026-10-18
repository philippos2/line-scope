"""Explicit product loss scopes; no inferred rate or factory-wide guarantee."""

from decimal import Decimal, localcontext

from .canonical import normalize_timestamp, normalize_uuid
from .input_values import exact, quantity, text


def normalize_losses(values):
    if type(values) is not list or not 1 <= len(values) <= 30:
        raise ValueError("One to thirty incident loss scopes required")
    result = []
    for value in values:
        exact(
            value,
            {"scope_key", "product_id", "loss_per_hour", "independent", "source", "certainty"},
        )
        if type(value["independent"]) is not bool or value["certainty"] not in (
            "ESTIMATED",
            "CONFIRMED",
        ):
            raise ValueError("Explicit independence and certainty required")
        result.append(
            {
                **value,
                "scope_key": text(value["scope_key"], 100),
                "product_id": normalize_uuid(value["product_id"]),
                "loss_per_hour": quantity(value["loss_per_hour"], nullable=True),
                "source": text(value["source"]),
            }
        )
    if len({row["scope_key"] for row in result}) != len(result):
        raise ValueError("Duplicate incident loss scope")
    return sorted(result, key=lambda row: row["scope_key"])


def normalize_selection(value):
    exact(value, {"equipment_ids", "economic_input_ids", "period_start", "period_end"})
    result = dict(value)
    for key, minimum in (("equipment_ids", 1), ("economic_input_ids", 0)):
        if type(value[key]) is not list or not minimum <= len(value[key]) <= 10:
            raise ValueError("Bounded explicit incident selection required")
        result[key] = sorted(normalize_uuid(v) for v in value[key])
        if len(set(result[key])) != len(result[key]):
            raise ValueError("Duplicate incident selection")
    for key in ("period_start", "period_end"):
        result[key] = normalize_timestamp(value[key])
    if result["period_start"] >= result["period_end"]:
        raise ValueError("Increasing incident evaluation period required")
    return result


def aggregate(impacts, records, period):
    """Deduplicate global loss scopes, excluding every conflicting assertion."""
    period = tuple(normalize_timestamp(value) for value in period)
    groups, missing = {}, []
    selected = {row["equipment_id"] for row in impacts}
    for record in records:
        if record["equipment_id"] not in selected:
            raise ValueError("Economic input equipment is outside incident selection")
    for impact in impacts:
        identifier = impact["equipment_id"]
        products = set(impact["product_ids"])
        if not impact["complete"]:
            missing.append({"equipment_id": identifier, "reason": "INCOMPLETE_GRAPH"})
        if impact["state_code"] == "RUNNING":
            continue  # No current stoppage assertion; not proof of zero actual damage.
        if impact["state_code"] != "STOPPED":
            missing.append({"equipment_id": identifier, "reason": "STOPPAGE_APPLICABILITY_UNKNOWN"})
            continue
        rows = [r for r in records if r["equipment_id"] == identifier]
        covered = set()
        if len(rows) != 1:
            missing.append({"equipment_id": identifier, "reason": "SELECT_ONE_ECONOMIC_INPUT"})
            continue
        (record,) = rows
        payload = record["payload"]
        if (payload["period_start"], payload["period_end"]) != period:
            missing.append({"equipment_id": identifier, "reason": "PERIOD_MISMATCH"})
            continue
        for item in payload.get("incident_losses", []):
            if item["product_id"] not in products:
                missing.append(
                    {
                        "equipment_id": identifier,
                        "scope_key": item["scope_key"],
                        "reason": "PRODUCT_OUTSIDE_IMPACT",
                    }
                )
                continue
            covered.add(item["product_id"])
            groups.setdefault(item["scope_key"], []).append(
                {
                    "value": item,
                    "economic_input_id": record["economic_input_id"],
                    "version": record["version"],
                    "equipment_id": identifier,
                }
            )
        for product in sorted(products - covered):
            missing.append(
                {"equipment_id": identifier, "product_id": product, "reason": "MISSING_LOSS_SCOPE"}
            )
    details = []
    with localcontext() as context:
        context.prec = 64
        subtotal = Decimal(0)
        for key, assertions in sorted(groups.items()):
            item = assertions[0]["value"]
            reason = (
                "CONFLICTING_SCOPE"
                if any(row["value"] != item for row in assertions)
                else "UNKNOWN_RATE"
                if item["loss_per_hour"] is None
                else "NONINDEPENDENT_SCOPE"
                if not item["independent"]
                else None
            )
            if reason:
                missing.append({"scope_key": key, "reason": reason})
            else:
                subtotal += Decimal(item["loss_per_hour"])
            details.append(
                {
                    **item,
                    "included_in_subtotal": reason is None,
                    "excluded_reason": reason,
                    "counted_times": 0 if reason else 1,
                    "assertions": assertions,
                }
            )
    applicable = any(row["state_code"] == "STOPPED" and row["product_ids"] for row in impacts)
    complete = applicable and not missing and bool(details)
    return {
        "currency": "JPY",
        "unit": "JPY/hour",
        "basis": "REGISTERED_STOPPAGE_ESTIMATE",
        "scope": "SELECTED_EQUIPMENT_REACHABLE_PRODUCTS_ONLY",
        "loss_per_hour": format(subtotal, "f") if complete else None,
        "known_subtotal_per_hour": format(subtotal, "f")
        if any(row["included_in_subtotal"] for row in details)
        else None,
        "complete": complete,
        "status": "ESTIMATED" if complete else "UNKNOWN",
        "items": details,
        "missing_information": missing,
        "formula": "sum(each consistent explicitly independent global loss scope once)",
        "actual_damage_confirmed": False,
        "cumulative_loss": None,
        "not_evaluated": [
            "actual_production_loss",
            "operational_recovery",
            "equipment_wide_safety",
        ],
    }
