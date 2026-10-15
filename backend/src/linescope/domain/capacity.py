"""Registered single-product constant-rate evaluation, independent of Graph or money."""

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

from .canonical import normalize_timestamp, normalize_uuid
from .input_values import exact, quantity, text

INPUT_FIELDS = {"input_code", "equipment_id", "product_id", "payload"}
RECORD_FIELDS = INPUT_FIELDS | {"capacity_input_id", "version"}
RATES = {"required_rate", "normal_rate", "used_rate", "reserved_rate"}
PAYLOAD_FIELDS = RATES | {
    "period_start",
    "period_end",
    "quantity_unit",
    "loads_independent",
    "loads_complete",
    "compatible",
    "source",
    "certainty",
    "recovery",
}
RECOVERY_FIELDS = {
    "buffer",
    "stopped_at",
    "constant_flow",
    "no_other_allocations",
    "recovery_meets_demand",
}


def normalize_payload(value):
    exact(value, PAYLOAD_FIELDS)
    start, end = (
        normalize_timestamp(value["period_start"]),
        normalize_timestamp(value["period_end"]),
    )
    if start >= end:
        raise ValueError("An increasing common evaluation period is required")
    for key in ("loads_independent", "loads_complete"):
        if type(value[key]) is not bool:
            raise ValueError("Explicit load attestations are required")
    if value["compatible"] is not None and type(value["compatible"]) is not bool:
        raise ValueError("Compatibility must be true, false or unknown")
    if value["certainty"] not in ("ESTIMATED", "CONFIRMED"):
        raise ValueError("Invalid certainty")
    recovery = value["recovery"]
    if recovery is not None:
        exact(recovery, RECOVERY_FIELDS)
        stopped = normalize_timestamp(recovery["stopped_at"])
        if not start <= stopped < end:
            raise ValueError("Stop start must lie within the common period")
        if any(
            type(recovery[key]) is not bool for key in RECOVERY_FIELDS - {"buffer", "stopped_at"}
        ):
            raise ValueError("Explicit recovery assumptions are required")
        recovery = {
            **recovery,
            "buffer": quantity(recovery["buffer"], nullable=True),
            "stopped_at": stopped,
        }
    return {
        **value,
        **{key: quantity(value[key], nullable=True) for key in RATES},
        "period_start": start,
        "period_end": end,
        "quantity_unit": text(value["quantity_unit"], 40),
        "source": text(value["source"]),
        "recovery": recovery,
    }


def normalize_input(value):
    exact(value, INPUT_FIELDS)
    return {
        "input_code": text(value["input_code"], 100),
        "equipment_id": normalize_uuid(value["equipment_id"]),
        "product_id": normalize_uuid(value["product_id"]),
        "payload": normalize_payload(value["payload"]),
    }


def normalize_record(value):
    exact(value, RECORD_FIELDS)
    if type(value["version"]) is not int or not 1 <= value["version"] <= 2**63 - 1:
        raise ValueError("Invalid capacity version")
    return {
        **normalize_input({key: value[key] for key in INPUT_FIELDS}),
        "capacity_input_id": normalize_uuid(value["capacity_input_id"]),
        "version": value["version"],
    }


def capacity_target(value, current=None):
    normalized = normalize_input(value)
    before = normalize_record(dict(current)) if current is not None else None
    after = normalize_record(
        {
            **normalized,
            "capacity_input_id": before["capacity_input_id"] if before else str(uuid4()),
            "version": before["version"] + 1 if before else 1,
        }
    )
    return validate_target(
        {
            "target_type": "CapacityInput",
            "target_id": after["capacity_input_id"],
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
    if value["target_type"] != "CapacityInput" or value["operation_type"] not in {
        "CREATE",
        "UPDATE",
    }:
        raise ValueError("Invalid capacity operation")
    after = normalize_record(value["after"])
    if normalize_uuid(value["target_id"]) != after["capacity_input_id"] or value[
        "business_key"
    ] != {"input_code": after["input_code"]}:
        raise ValueError("Capacity identity mismatch")
    if value["operation_type"] == "CREATE":
        if (
            value["before"] is not None
            or value["expected_version"] is not None
            or after["version"] != 1
        ):
            raise ValueError("Invalid capacity CREATE")
        before = None
    else:
        before = normalize_record(value["before"])
        if (
            any(
                before[key] != after[key]
                for key in {"capacity_input_id", "input_code", "equipment_id", "product_id"}
            )
            or before["payload"] == after["payload"]
        ):
            raise ValueError("Immutable capacity identity or unchanged payload")
        if (
            type(value["expected_version"]) is not int
            or value["expected_version"] != before["version"]
            or after["version"] != before["version"] + 1
        ):
            raise ValueError("Capacity version mismatch")
    return {**value, "target_id": after["capacity_input_id"], "before": before, "after": after}


def calculate(value):
    payload = normalize_payload(value)
    missing = sorted(key for key in RATES if payload[key] is None)
    missing += [key for key in ("loads_independent", "loads_complete") if not payload[key]]
    result = {
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
        "quantity_unit": payload["quantity_unit"],
        "rate_time_unit": "hour",
        "required_rate": payload["required_rate"],
        "available_rate": None,
        "shortage_rate": None,
        "capacity_status": "UNKNOWN",
        "compatibility": payload["compatible"],
        "missing_information": missing,
        "source": payload["source"],
        "certainty": payload["certainty"],
        "feasibility": "UNKNOWN",
        "recovery_status": "UNKNOWN",
        "permissible_downtime_hours": None,
        "recovery_deadline": None,
        "recovery_assumptions": payload["recovery"],
    }
    if missing:
        return result
    with localcontext() as context:
        context.prec = 64
        available = (
            Decimal(payload["normal_rate"])
            - Decimal(payload["used_rate"])
            - Decimal(payload["reserved_rate"])
        )
        if available < 0:
            result["missing_information"].append("load_exceeds_normal_capacity")
            return result
        shortage = max(Decimal(0), Decimal(payload["required_rate"]) - available)
        result.update(available_rate=format(available, "f"), shortage_rate=format(shortage, "f"))
        if payload["compatible"] is None:
            result["missing_information"].append("product_compatibility")
        else:
            result["capacity_status"] = (
                "INCOMPATIBLE"
                if not payload["compatible"]
                else "INSUFFICIENT"
                if shortage > 0
                else "SUFFICIENT"
            )
        recovery = payload["recovery"]
        # A buffer deadline is conditional on compatible supply and all constant-flow assumptions.
        if (
            payload["compatible"] is not True
            or recovery is None
            or recovery["buffer"] is None
            or shortage <= 0
            or not all(
                recovery[key]
                for key in ("constant_flow", "no_other_allocations", "recovery_meets_demand")
            )
        ):
            return result
        buffer = Decimal(recovery["buffer"])
        # Floor the deadline to microseconds: rounding must never grant extra downtime.
        micros = int(buffer * Decimal(3600000000) // shortage)
        start = datetime.fromisoformat(recovery["stopped_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(payload["period_end"].replace("Z", "+00:00"))
        span = end - start
        period_micros = (span.days * 86400 + span.seconds) * 1000000 + span.microseconds
        if micros > period_micros:
            result["missing_information"].append("recovery_deadline_outside_valid_period")
            return result
        # Display hours to six decimals, rounded down, independently of timestamp precision.
        hours = (buffer * Decimal(1000000) // shortage) / Decimal(1000000)
        result.update(
            recovery_status="CONDITIONAL",
            permissible_downtime_hours=format(hours, "f"),
            recovery_deadline=normalize_timestamp(
                (start + timedelta(microseconds=micros)).isoformat()
            ),
        )
    return result
