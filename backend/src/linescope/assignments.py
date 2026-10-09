"""Pure equipment-assignment interval replacement; no DB writes or approval.

Prepare must supply a complete, consistent set of the operation's assignments,
including inactive rows for business-key reuse. The parent version, full active
set, permissions and Graph constraints are handled by the later Prepare layer.
"""

from uuid import uuid4

from .canonical import normalize_id_set, normalize_timestamp, normalize_uuid

FIELDS = {
    "assignment_id",
    "production_operation_id",
    "equipment_id",
    "effective_from",
    "effective_to",
    "active",
    "version",
}
KEY_FIELDS = {"production_operation_id", "equipment_id", "effective_from"}
TARGET_FIELDS = {
    "target_type",
    "target_id",
    "business_key",
    "operation_type",
    "before",
    "after",
    "expected_version",
}
TARGET_TYPE = "ProductionOperationEquipmentAssignment"
MAX_VERSION = 2**63 - 1


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid assignment fields")


def _record(value):
    _exact(value, FIELDS)
    if type(value["active"]) is not bool:
        raise ValueError("Assignment active must be boolean")
    if type(value["version"]) is not int or not 1 <= value["version"] <= MAX_VERSION:
        raise ValueError("Assignment version must be a positive BIGINT")
    start = normalize_timestamp(value["effective_from"])
    end = normalize_timestamp(value["effective_to"]) if value["effective_to"] is not None else None
    if end is not None and start >= end:
        raise ValueError("Assignment interval must be nonempty")
    return {
        "assignment_id": normalize_uuid(value["assignment_id"]),
        "production_operation_id": normalize_uuid(value["production_operation_id"]),
        "equipment_id": normalize_uuid(value["equipment_id"]),
        "effective_from": start,
        "effective_to": end,
        "active": value["active"],
        "version": value["version"],
    }


def _key(record):
    return {field: record[field] for field in KEY_FIELDS}


def validate_assignment_target(value):
    """Validate the concrete CREATE/UPDATE/DISABLE diff, including all versions."""
    _exact(value, TARGET_FIELDS)
    if value["target_type"] != TARGET_TYPE:
        raise ValueError("Invalid assignment target type")
    after = _record(value["after"])
    identifier = normalize_uuid(value["target_id"])
    _exact(value["business_key"], KEY_FIELDS)
    business_key = {
        "production_operation_id": normalize_uuid(value["business_key"]["production_operation_id"]),
        "equipment_id": normalize_uuid(value["business_key"]["equipment_id"]),
        "effective_from": normalize_timestamp(value["business_key"]["effective_from"]),
    }
    if identifier != after["assignment_id"] or business_key != _key(after):
        raise ValueError("Assignment target ID or business key disagrees")
    operation = value["operation_type"]
    before, expected = value["before"], value["expected_version"]
    if operation == "CREATE":
        if (
            before is not None
            or expected is not None
            or after["version"] != 1
            or not after["active"]
        ):
            raise ValueError("Invalid assignment CREATE")
    elif operation in ("UPDATE", "DISABLE"):
        before = _record(before)
        if (
            type(expected) is not int
            or expected != before["version"]
            or after["version"] != expected + 1
        ):
            raise ValueError("Assignment versions disagree")
        if before["assignment_id"] != identifier or _key(before) != business_key:
            raise ValueError("Assignment immutable fields changed")
        if operation == "DISABLE":
            if (
                not before["active"]
                or after["active"]
                or before["effective_to"] != after["effective_to"]
            ):
                raise ValueError("Invalid assignment DISABLE")
        elif not after["active"] or (
            before["active"] and before["effective_to"] == after["effective_to"]
        ):
            raise ValueError("Assignment UPDATE must change an active interval or reactivate")
    else:
        raise ValueError("Unsupported assignment operation")
    return {
        "target_type": TARGET_TYPE,
        "target_id": identifier,
        "business_key": business_key,
        "operation_type": operation,
        "before": before,
        "after": after,
        "expected_version": expected,
    }


def _overlaps(start, end, other_start, other_end):
    return (end is None or other_start < end) and (other_end is None or start < other_end)


def _source(operation_id, assignments):
    if type(assignments) is not list:
        raise ValueError("Assignments must be a complete list")
    rows, ids, keys = [], set(), set()
    for value in assignments:
        if type(value) is not dict:
            raise ValueError("Assignment must be a record")
        row = _record(
            {key: item for key, item in value.items() if key not in {"created_at", "updated_at"}}
        )
        key = (row["equipment_id"], row["effective_from"])
        if row["production_operation_id"] != operation_id:
            raise ValueError("Assignment belongs to another operation")
        if row["assignment_id"] in ids or key in keys:
            raise ValueError("Duplicate source assignment ID or business key")
        ids.add(row["assignment_id"])
        keys.add(key)
        rows.append(row)
    rows.sort(key=lambda row: (row["equipment_id"], row["effective_from"]))
    previous = None
    for row in rows:
        if not row["active"]:
            continue
        if (
            previous is not None
            and previous["equipment_id"] == row["equipment_id"]
            and _overlaps(
                previous["effective_from"],
                previous["effective_to"],
                row["effective_from"],
                row["effective_to"],
            )
        ):
            raise ValueError("Overlapping active source assignments")
        previous = row
    return rows


def replacement_assignment_targets(production_operation_id, current_assignments, replacement):
    """Replace the Equipment set only within explicit [from,to); NULL means infinity.

    Returns concrete, server-ID-fixed targets. An empty result means no assignment
    change. This does not build a parent Snapshot or increment the parent version.
    """
    operation_id = normalize_uuid(production_operation_id)
    _exact(replacement, {"effective_from", "effective_to", "equipment_ids"})
    start = normalize_timestamp(replacement["effective_from"])
    end = (
        normalize_timestamp(replacement["effective_to"])
        if replacement["effective_to"] is not None
        else None
    )
    if end is not None and start >= end:
        raise ValueError("Replacement interval must be nonempty")
    equipment_ids = normalize_id_set(replacement["equipment_ids"])
    rows = _source(operation_id, current_assignments)
    desired = {
        (row["equipment_id"], row["effective_from"]): row["effective_to"]
        for row in rows
        if row["active"]
    }
    wanted = set(equipment_ids)
    for row in rows:
        equipment, old_start, old_end = (
            row["equipment_id"],
            row["effective_from"],
            row["effective_to"],
        )
        if (
            not row["active"]
            or equipment in wanted
            or not _overlaps(old_start, old_end, start, end)
        ):
            continue
        del desired[(equipment, old_start)]
        if old_start < start:
            desired[(equipment, old_start)] = start
        if end is not None and (old_end is None or end < old_end):
            desired[(equipment, end)] = old_end
    # Existing desired Equipment intervals stay intact; fill only uncovered gaps.
    for equipment in equipment_ids:
        cursor = start
        for row in rows:
            if (
                not row["active"]
                or row["equipment_id"] != equipment
                or not _overlaps(row["effective_from"], row["effective_to"], start, end)
            ):
                continue
            if cursor < row["effective_from"]:
                desired[(equipment, cursor)] = row["effective_from"]
            if row["effective_to"] is None:
                cursor = None
                break
            cursor = max(cursor, row["effective_to"])
            if end is not None and cursor >= end:
                break
        if cursor is not None and (end is None or cursor < end):
            desired[(equipment, cursor)] = end
    by_key = {(row["equipment_id"], row["effective_from"]): row for row in rows}
    targets = []
    for key, desired_end in sorted(desired.items()):
        before = by_key.get(key)
        if before is not None and before["active"] and before["effective_to"] == desired_end:
            continue
        if before is None:
            after = {
                "assignment_id": str(uuid4()),
                "production_operation_id": operation_id,
                "equipment_id": key[0],
                "effective_from": key[1],
                "effective_to": desired_end,
                "active": True,
                "version": 1,
            }
            operation, expected = "CREATE", None
        else:
            after = {
                **before,
                "effective_to": desired_end,
                "active": True,
                "version": before["version"] + 1,
            }
            operation, expected = "UPDATE", before["version"]
        targets.append(
            validate_assignment_target(
                {
                    "target_type": TARGET_TYPE,
                    "target_id": after["assignment_id"],
                    "business_key": _key(after),
                    "operation_type": operation,
                    "before": before,
                    "after": after,
                    "expected_version": expected,
                }
            )
        )
    for before in rows:
        if before["active"] and (before["equipment_id"], before["effective_from"]) not in desired:
            after = {**before, "active": False, "version": before["version"] + 1}
            targets.append(
                validate_assignment_target(
                    {
                        "target_type": TARGET_TYPE,
                        "target_id": after["assignment_id"],
                        "business_key": _key(after),
                        "operation_type": "DISABLE",
                        "before": before,
                        "after": after,
                        "expected_version": before["version"],
                    }
                )
            )
    new_ids = [target["target_id"] for target in targets if target["operation_type"] == "CREATE"]
    if len(set(new_ids)) != len(new_ids) or set(new_ids) & {row["assignment_id"] for row in rows}:
        raise ValueError("Generated assignment ID collision")
    return sorted(targets, key=lambda target: (target["target_type"], target["target_id"]))
