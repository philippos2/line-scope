"""Explicit economic estimates; no fixture, inferred downtime or feasibility claim."""

from datetime import datetime
from decimal import Decimal, localcontext
from uuid import uuid4

from .canonical import normalize_timestamp, normalize_uuid
from .cost_recovery import calculate as cost_recovery_calculation
from .cost_recovery import normalize as normalize_recovery
from .input_values import exact, quantity, text

INPUT_FIELDS = {"input_code", "equipment_id", "payload"}
PAYLOAD_FIELDS = {"period_start", "period_end", "operating_hours", "currency", "options"}
ITEM_FIELDS = {
    "key",
    "kind",
    "amount",
    "hours",
    "independent",
    "source",
    "certainty",
    "valid_from",
    "valid_to",
}
RECORD_FIELDS = INPUT_FIELDS | {"economic_input_id", "version"}


def normalize_payload(value):
    exact(
        value,
        PAYLOAD_FIELDS
        | ({"cost_recovery"} if type(value) is dict and "cost_recovery" in value else set()),
    )
    start, end = (
        normalize_timestamp(value["period_start"]),
        normalize_timestamp(value["period_end"]),
    )
    hours = quantity(value["operating_hours"])
    if start >= end or value["currency"] != "JPY":
        raise ValueError("A common increasing period and JPY currency are required")
    span = datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(
        start.replace("Z", "+00:00")
    )
    # Integer microseconds avoid binary float or a guessed hours/day calendar.
    micros = (span.days * 86400 + span.seconds) * 1000000 + span.microseconds
    if int(Decimal(hours) * 1000000) * 3600 > micros:
        raise ValueError("Operating hours exceed the common period")
    options = value["options"]
    if type(options) is not list or len(options) != 3:
        raise ValueError("REPAIR, REPLACE and CONTINUE estimates are required")
    normalized = []
    for option in options:
        exact(option, {"option", "complete", "items"})
        if (
            type(option["option"]) is not str
            or option["option"] not in {"REPAIR", "REPLACE", "CONTINUE"}
            or type(option["complete"]) is not bool
        ):
            raise ValueError("Invalid option or completeness attestation")
        if type(option["items"]) is not list or not 1 <= len(option["items"]) <= 30:
            raise ValueError("One to thirty explicit cost items are required")
        items = []
        for item in option["items"]:
            exact(item, ITEM_FIELDS)
            if type(item["kind"]) is not str or item["kind"] not in {
                "DIRECT",
                "STOPPAGE",
                "DEGRADATION",
            }:
                raise ValueError("Invalid economic item kind")
            if type(item["independent"]) is not bool or item["certainty"] not in (
                "ESTIMATED",
                "CONFIRMED",
            ):
                raise ValueError("Explicit independence and certainty are required")
            since, until = (
                normalize_timestamp(item["valid_from"]),
                normalize_timestamp(item["valid_to"]),
            )
            if since > start or until < end:
                raise ValueError("Each item must apply throughout the common period")
            amount = quantity(item["amount"], nullable=True)
            duration = quantity(item["hours"], nullable=True)
            if item["kind"] == "DIRECT":
                if duration is not None:
                    raise ValueError("Direct cost must not have loss hours")
            elif duration is not None and Decimal(duration) > Decimal(hours):
                raise ValueError("Loss hours exceed explicit operating hours")
            items.append(
                {
                    **item,
                    "key": text(item["key"], 100),
                    "source": text(item["source"]),
                    "amount": amount,
                    "hours": duration,
                    "valid_from": since,
                    "valid_to": until,
                }
            )
        # A key identifies a nonoverlapping business loss/cost scope, not a Graph path.
        if len({item["key"] for item in items}) != len(items):
            raise ValueError("Duplicate or overlapping economic scope key")
        normalized.append({**option, "items": sorted(items, key=lambda item: item["key"])})
    if {option["option"] for option in normalized} != {"REPAIR", "REPLACE", "CONTINUE"}:
        raise ValueError("Duplicate economic option")
    result = {
        "period_start": start,
        "period_end": end,
        "operating_hours": hours,
        "currency": "JPY",
        "options": sorted(normalized, key=lambda option: option["option"]),
    }
    if "cost_recovery" in value:
        result["cost_recovery"] = normalize_recovery(
            value["cost_recovery"], operating_hours=hours, period_micros=micros
        )
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
        raise ValueError("Invalid economic version")
    return {
        **normalize_input({key: value[key] for key in INPUT_FIELDS}),
        "economic_input_id": normalize_uuid(value["economic_input_id"]),
        "version": value["version"],
    }


def economic_target(value, current=None):
    normalized = normalize_input(value)
    before = normalize_record(dict(current)) if current is not None else None
    after = normalize_record(
        {
            **normalized,
            "economic_input_id": before["economic_input_id"] if before else str(uuid4()),
            "version": before["version"] + 1 if before else 1,
        }
    )
    return validate_target(
        {
            "target_type": "EconomicInput",
            "target_id": after["economic_input_id"],
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
    if value["target_type"] != "EconomicInput" or value["operation_type"] not in {
        "CREATE",
        "UPDATE",
    }:
        raise ValueError("Invalid economic operation")
    after = normalize_record(value["after"])
    if normalize_uuid(value["target_id"]) != after["economic_input_id"] or value[
        "business_key"
    ] != {"input_code": after["input_code"]}:
        raise ValueError("Economic identity mismatch")
    if value["operation_type"] == "CREATE":
        if (
            value["before"] is not None
            or value["expected_version"] is not None
            or after["version"] != 1
        ):
            raise ValueError("Invalid economic CREATE")
        before = None
    else:
        before = normalize_record(value["before"])
        if (
            any(
                before[key] != after[key]
                for key in {"economic_input_id", "input_code", "equipment_id"}
            )
            or before["payload"] == after["payload"]
        ):
            raise ValueError("Immutable economic identity or unchanged payload")
        if (
            type(value["expected_version"]) is not int
            or value["expected_version"] != before["version"]
            or after["version"] != before["version"] + 1
        ):
            raise ValueError("Economic version mismatch")
    return {**value, "target_id": after["economic_input_id"], "before": before, "after": after}


def calculate(value):
    payload = normalize_payload(value)
    results = []
    # Bounds above need < 50 digits even after 30 rate*time additions; never round.
    with localcontext() as context:
        context.prec = 64
        for option in payload["options"]:
            subtotal = Decimal(0)
            unknown = []
            details = []
            for item in option["items"]:
                amount = Decimal(item["amount"]) if item["amount"] is not None else None
                if item["kind"] != "DIRECT":
                    amount = (
                        amount * Decimal(item["hours"])
                        if amount is not None and item["hours"] is not None
                        else None
                    )
                included = amount is not None and item["independent"]
                if included:
                    subtotal += amount
                else:
                    unknown.append(item["key"])
                details.append(
                    {
                        "key": item["key"],
                        "kind": item["kind"],
                        "amount_jpy": format(amount, "f") if amount is not None else None,
                        "included_in_subtotal": included,
                        "source": item["source"],
                        "certainty": item["certainty"],
                    }
                )
            results.append(
                {
                    "option": option["option"],
                    "known_subtotal_jpy": format(subtotal, "f"),
                    "total_jpy": format(subtotal, "f")
                    if option["complete"] and not unknown
                    else None,
                    "complete": option["complete"],
                    "unknown_or_nonindependent_keys": unknown,
                    "items": details,
                }
            )
    return {
        "currency": "JPY",
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
        "operating_hours": payload["operating_hours"],
        "options": results,
        "feasibility": "UNKNOWN",
        "recommendation": None,
        "simple_cost_recovery": cost_recovery_calculation(payload),
    }
