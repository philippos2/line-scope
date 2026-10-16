"""Approved registered declarations, not live sensing or equipment control."""

from uuid import uuid4

from .canonical import normalize_timestamp, normalize_uuid
from .input_values import exact, text

INPUT_FIELDS = {"input_code", "equipment_id", "payload"}
RECORD_FIELDS = INPUT_FIELDS | {"safety_input_id", "version"}
PAYLOAD_FIELDS = {
    "period_start",
    "period_end",
    "observation",
    "criterion",
    "source",
    "conditions",
    "decision",
    "certainty",
    "risk_notes",
}


def normalize_payload(value):
    exact(value, PAYLOAD_FIELDS)
    start, end = (
        normalize_timestamp(value["period_start"]),
        normalize_timestamp(value["period_end"]),
    )
    if start >= end:
        raise ValueError("An increasing validity period is required")
    if value["decision"] not in ("STOP_REQUIRED", "CONDITIONAL", "UNKNOWN") or value[
        "certainty"
    ] not in ("ESTIMATED", "CONFIRMED"):
        raise ValueError("Invalid safety declaration")
    result = {**value, "period_start": start, "period_end": end, "source": text(value["source"])}
    for key in ("observation", "criterion", "conditions", "risk_notes"):
        result[key] = text(value[key]) if value[key] is not None else None
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
        raise ValueError("Invalid safety version")
    return {
        **normalize_input({key: value[key] for key in INPUT_FIELDS}),
        "safety_input_id": normalize_uuid(value["safety_input_id"]),
        "version": value["version"],
    }


def safety_target(value, current=None):
    normalized = normalize_input(value)
    before = normalize_record(dict(current)) if current is not None else None
    after = normalize_record(
        {
            **normalized,
            "safety_input_id": before["safety_input_id"] if before else str(uuid4()),
            "version": before["version"] + 1 if before else 1,
        }
    )
    return validate_target(
        {
            "target_type": "SafetyInput",
            "target_id": after["safety_input_id"],
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
    if value["target_type"] != "SafetyInput" or value["operation_type"] not in {
        "CREATE",
        "UPDATE",
    }:
        raise ValueError("Invalid safety operation")
    after = normalize_record(value["after"])
    if normalize_uuid(value["target_id"]) != after["safety_input_id"] or value["business_key"] != {
        "input_code": after["input_code"]
    }:
        raise ValueError("Safety identity mismatch")
    if value["operation_type"] == "CREATE":
        if (
            value["before"] is not None
            or value["expected_version"] is not None
            or after["version"] != 1
        ):
            raise ValueError("Invalid safety CREATE")
        before = None
    else:
        before = normalize_record(value["before"])
        if (
            any(
                before[key] != after[key]
                for key in {"safety_input_id", "input_code", "equipment_id"}
            )
            or before["payload"] == after["payload"]
        ):
            raise ValueError("Immutable safety identity or unchanged payload")
        if (
            type(value["expected_version"]) is not int
            or value["expected_version"] != before["version"]
            or after["version"] != before["version"] + 1
        ):
            raise ValueError("Safety version mismatch")
    return {**value, "target_id": after["safety_input_id"], "before": before, "after": after}


def calculate(value, evaluated_at):
    p = normalize_payload(value)
    at = normalize_timestamp(evaluated_at)
    missing = [key for key in ("observation", "criterion") if p[key] is None]
    active = p["period_start"] <= at < p["period_end"]
    if not active:
        missing.append("outside_valid_period")
    status = "UNKNOWN"
    if active and p["decision"] == "STOP_REQUIRED":
        status = "STOP_REQUIRED"
    elif active and p["decision"] == "CONDITIONAL":
        if p["conditions"] is None:
            missing.append("continued_operation_conditions")
        if p["certainty"] != "CONFIRMED":
            missing.append("confirmed_basis")
        if not missing:
            status = "CONDITIONAL"
    elif p["decision"] == "UNKNOWN":
        missing.append("declared_safety_decision")
    return {
        "status": status,
        "evaluated_at": at,
        "period_start": p["period_start"],
        "period_end": p["period_end"],
        "declared_decision": p["decision"],
        "continue_candidate": "EXCLUDED"
        if status == "STOP_REQUIRED"
        else "CONDITIONAL"
        if status == "CONDITIONAL"
        else "UNASSESSED",
        "missing_information": missing,
        "source": p["source"],
        "criterion": p["criterion"],
        "observation": p["observation"],
        "conditions": p["conditions"],
        "risk_notes": p["risk_notes"],
        "certainty": p["certainty"],
        "residual_risk": "UNKNOWN",
        "operational_permission": False,
        "assessment_scope": "SELECTED_INPUT_ONLY",
    }
