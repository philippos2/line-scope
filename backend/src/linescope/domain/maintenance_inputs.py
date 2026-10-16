"""Approved registered declarations, not live sensing or equipment control."""

from decimal import Decimal
from uuid import uuid4

from .canonical import normalize_timestamp, normalize_uuid
from .input_values import exact, quantity, text

INPUT_FIELDS = {"input_code", "equipment_id", "payload"}
RECORD_FIELDS = INPUT_FIELDS | {"maintenance_input_id", "version"}
KINDS = {"REPAIR_PLAN", "REPLACEMENT_PLAN", "INTERIM_PLAN", "FAILURE_RECORD", "REPAIR_RECORD"}
QUANTITIES = {
    "lead_time_hours",
    "work_hours",
    "downtime_hours",
    "direct_cost_jpy",
    "past_loss_jpy",
    "replacement_cost_jpy",
}
PAYLOAD_FIELDS = {
    "kind",
    "period_start",
    "period_end",
    "source",
    "details",
    "risk_notes",
    "maintenance_plan_id",
    "interim_until",
    "include_replacement_cost",
} | QUANTITIES


def normalize_payload(value):
    exact(value, PAYLOAD_FIELDS)
    start, end = (
        normalize_timestamp(value["period_start"]),
        normalize_timestamp(value["period_end"]),
    )
    if start >= end or value["kind"] not in KINDS:
        raise ValueError("Invalid maintenance classification or period")
    result = {
        **value,
        "period_start": start,
        "period_end": end,
        "source": text(value["source"]),
        "details": text(value["details"]),
    }
    result["risk_notes"] = text(value["risk_notes"]) if value["risk_notes"] is not None else None
    for key in QUANTITIES:
        result[key] = quantity(value[key], nullable=True)
    result["maintenance_plan_id"] = (
        normalize_uuid(value["maintenance_plan_id"])
        if value["maintenance_plan_id"] is not None
        else None
    )
    result["interim_until"] = (
        normalize_timestamp(value["interim_until"]) if value["interim_until"] is not None else None
    )
    if result["interim_until"] is not None and not start < result["interim_until"] <= end:
        raise ValueError("Interim end must be within the explicit evaluation period")
    included = value["include_replacement_cost"]
    if included is not None and type(included) is not bool:
        raise ValueError("Replacement cost inclusion must be explicit or unknown")
    if value["kind"].endswith("_RECORD"):
        if any(
            value[key] is not None
            for key in (
                "lead_time_hours",
                "interim_until",
                "include_replacement_cost",
                "replacement_cost_jpy",
            )
        ):
            raise ValueError("Historical records cannot declare future plan costs or lead time")
    elif value["past_loss_jpy"] is not None:
        raise ValueError("Past loss belongs to an explicit historical record")
    return result


def normalize_input(value):
    exact(value, INPUT_FIELDS)
    return {
        "input_code": text(value["input_code"], 100),
        "equipment_id": normalize_uuid(value["equipment_id"]),
        "payload": normalize_payload(value["payload"]),
    }


def normalize_record(value):
    exact(value, RECORD_FIELDS)
    if type(value["version"]) is not int or not 1 <= value["version"] <= 2**63 - 1:
        raise ValueError("Invalid maintenance version")
    return {
        **normalize_input({key: value[key] for key in INPUT_FIELDS}),
        "maintenance_input_id": normalize_uuid(value["maintenance_input_id"]),
        "version": value["version"],
    }


def maintenance_input_target(value, current=None):
    normalized = normalize_input(value)
    before = normalize_record(dict(current)) if current is not None else None
    after = normalize_record(
        {
            **normalized,
            "maintenance_input_id": before["maintenance_input_id"] if before else str(uuid4()),
            "version": before["version"] + 1 if before else 1,
        }
    )
    return validate_target(
        {
            "target_type": "MaintenanceInput",
            "target_id": after["maintenance_input_id"],
            "business_key": {"input_code": after["input_code"]},
            "operation_type": "UPDATE" if before else "CREATE",
            "before": before,
            "after": after,
            "expected_version": before["version"] if before else None,
        }
    )


def validate_target(value):
    exact(
        value,
        {
            "target_type",
            "target_id",
            "business_key",
            "operation_type",
            "before",
            "after",
            "expected_version",
        },
    )
    if value["target_type"] != "MaintenanceInput" or value["operation_type"] not in {
        "CREATE",
        "UPDATE",
    }:
        raise ValueError("Invalid maintenance operation")
    after = normalize_record(value["after"])
    if normalize_uuid(value["target_id"]) != after["maintenance_input_id"] or value[
        "business_key"
    ] != {"input_code": after["input_code"]}:
        raise ValueError("Maintenance identity mismatch")
    if value["operation_type"] == "CREATE":
        if (
            value["before"] is not None
            or value["expected_version"] is not None
            or after["version"] != 1
        ):
            raise ValueError("Invalid maintenance CREATE")
        before = None
    else:
        before = normalize_record(value["before"])
        if (
            any(
                before[key] != after[key]
                for key in {"maintenance_input_id", "input_code", "equipment_id"}
            )
            or before["payload"] == after["payload"]
        ):
            raise ValueError("Immutable maintenance identity or unchanged payload")
        if (
            type(value["expected_version"]) is not int
            or value["expected_version"] != before["version"]
            or after["version"] != before["version"] + 1
        ):
            raise ValueError("Maintenance version mismatch")
    return {**value, "target_id": after["maintenance_input_id"], "before": before, "after": after}


def calculate(value, evaluated_at):
    p = normalize_payload(value)
    historical = p["kind"].endswith("_RECORD")
    missing = [key for key in ("work_hours", "downtime_hours", "direct_cost_jpy") if p[key] is None]
    if not historical and p["lead_time_hours"] is None:
        missing.append("lead_time_hours")
    if p["kind"] == "INTERIM_PLAN" and p["interim_until"] is None:
        missing.append("interim_until")
    if not historical and p["include_replacement_cost"] is None:
        missing.append("include_replacement_cost")
    if (
        not historical
        and p["include_replacement_cost"] is True
        and p["replacement_cost_jpy"] is None
    ):
        missing.append("replacement_cost_jpy")
    # Only explicitly supplied plan direct costs are added; no inferred downtime loss,
    # period proration, forecasts, or past-loss addition to a future option.
    subtotal = None
    if (
        not historical
        and p["direct_cost_jpy"] is not None
        and p["include_replacement_cost"] is not None
    ):
        if p["include_replacement_cost"] is False:
            subtotal = p["direct_cost_jpy"]
        elif p["replacement_cost_jpy"] is not None:
            subtotal = format(
                Decimal(p["direct_cost_jpy"]) + Decimal(p["replacement_cost_jpy"]), "f"
            )
    return {
        **p,
        "evaluated_at": normalize_timestamp(evaluated_at),
        "record_scope": "HISTORICAL" if historical else "PLAN_EVALUATION_PERIOD",
        "known_plan_direct_cost_subtotal_jpy": subtotal,
        "total_economic_impact_jpy": None,
        "future_failure_probability": None,
        "feasibility": "UNASSESSED",
        "missing_information": missing + ["future_failure_probability", "total_economic_impact"],
        "automatic_state_change": False,
        "assessment_scope": "SELECTED_INPUT_ONLY",
    }
