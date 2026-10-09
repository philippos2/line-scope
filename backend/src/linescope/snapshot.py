"""Canonical Snapshot v1 for equipment, maintenance, production and relations.

This pure construction/validation layer does not authorize, persist or execute
updates. Prepare must supply current PostgreSQL state and check permissions.
Other target categories are rejected until their schemas are implemented.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from uuid import uuid4

from .assignments import (
    normalize_operation_assignments,
    replacement_assignment_targets,
    validate_assignment_target,
)
from .canonical import canonical_json, normalize_timestamp, normalize_uuid, strict_json
from .execution import ExecutionContext
from .relations import validate_relation_target

MAX_VERSION = 2**63 - 1
STATE_CODES = {"RUNNING", "STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"}
TARGET_FIELDS = {
    "target_type",
    "target_id",
    "business_key",
    "operation_type",
    "before",
    "after",
    "expected_version",
}
ROOT_FIELDS = {"schema_version", "requester_id", "supersedes_update_request_id", "targets"}
CATEGORIES = {
    "EquipmentState": "EQUIPMENT_STATE",
    "MaintenancePlan": "MAINTENANCE",
    "MaintenanceRecord": "MAINTENANCE",
    "ProductionOperation": "PRODUCTION_OPERATION",
    "ProductionOperationEquipmentAssignment": "PRODUCTION_OPERATION",
    "DependencyRelation": "DEPENDENCY",
}


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid Snapshot fields")


def _version(value):
    if type(value) is not int or not 1 <= value <= MAX_VERSION:
        raise ValueError("Version must be a positive BIGINT")
    return value


def _state_record(value):
    _exact(value, {"equipment_id", "state_code", "version"})
    if type(value["state_code"]) is not str or value["state_code"] not in STATE_CODES:
        raise ValueError("Invalid equipment state")
    return {
        "equipment_id": normalize_uuid(value["equipment_id"]),
        "state_code": value["state_code"],
        "version": _version(value["version"]),
    }


def equipment_state_target(current, state_code):
    """Use a trusted current-state row; derive version and exclude audit time."""
    if type(current) is not dict:
        raise ValueError("Current state must be a record")
    before = _state_record({key: value for key, value in current.items() if key != "updated_at"})
    after = _state_record({**before, "state_code": state_code, "version": before["version"] + 1})
    if before["state_code"] == after["state_code"]:
        raise ValueError("Equipment state update must change a business value")
    return {
        "target_type": "EquipmentState",
        "target_id": before["equipment_id"],
        "business_key": {"equipment_id": before["equipment_id"]},
        "operation_type": "UPDATE",
        "before": before,
        "after": after,
        "expected_version": before["version"],
    }


def _state_target(value):
    _exact(value, TARGET_FIELDS)
    if value["target_type"] != "EquipmentState" or value["operation_type"] != "UPDATE":
        raise ValueError("Unsupported Snapshot target or operation")
    identifier = normalize_uuid(value["target_id"])
    _exact(value["business_key"], {"equipment_id"})
    business_id = normalize_uuid(value["business_key"]["equipment_id"])
    before = _state_record(value["before"])
    after = _state_record(value["after"])
    if {identifier, business_id, before["equipment_id"], after["equipment_id"]} != {identifier}:
        raise ValueError("Snapshot equipment IDs disagree")
    expected = _version(value["expected_version"])
    if before["version"] != expected or after["version"] != expected + 1:
        raise ValueError("Snapshot versions disagree")
    if before["state_code"] == after["state_code"]:
        raise ValueError("Equipment state update must change a business value")
    return {
        "target_type": "EquipmentState",
        "target_id": identifier,
        "business_key": {"equipment_id": identifier},
        "operation_type": "UPDATE",
        "before": before,
        "after": after,
        "expected_version": expected,
    }


PLAN_FIELDS = {
    "maintenance_plan_id",
    "plan_code",
    "equipment_id",
    "planned_start",
    "planned_end",
    "plan_status",
    "version",
}
PLAN_PATCH_FIELDS = {"planned_start", "planned_end", "plan_status"}


def _plan_record(value):
    _exact(value, PLAN_FIELDS)
    if type(value["plan_code"]) is not str:
        raise ValueError("Plan code must be text")
    if type(value["plan_status"]) is not str or value["plan_status"] not in {
        "PLANNED",
        "CANCELLED",
    }:
        raise ValueError("Invalid maintenance plan status")
    start = normalize_timestamp(value["planned_start"])
    end = normalize_timestamp(value["planned_end"])
    if start >= end:
        raise ValueError("Maintenance plan start must precede end")
    return {
        "maintenance_plan_id": normalize_uuid(value["maintenance_plan_id"]),
        "plan_code": value["plan_code"],
        "equipment_id": normalize_uuid(value["equipment_id"]),
        "planned_start": start,
        "planned_end": end,
        "plan_status": value["plan_status"],
        "version": _version(value["version"]),
    }


def maintenance_plan_target(current, patch):
    """Apply only Tool-contract fields to a trusted complete PostgreSQL row."""
    before = _plan_record(current)
    if type(patch) is not dict or not patch or not set(patch) <= PLAN_PATCH_FIELDS:
        raise ValueError("Invalid maintenance plan patch")
    after = _plan_record({**before, **patch, "version": before["version"] + 1})
    return _plan_target(
        {
            "target_type": "MaintenancePlan",
            "target_id": before["maintenance_plan_id"],
            "business_key": {"plan_code": before["plan_code"]},
            "operation_type": "UPDATE",
            "before": before,
            "after": after,
            "expected_version": before["version"],
        }
    )


def _plan_target(value):
    _exact(value, TARGET_FIELDS)
    if value["operation_type"] == "CREATE":
        return _create_target(
            value, "MaintenancePlan", _plan_record, "maintenance_plan_id", "plan_code"
        )
    if value["target_type"] != "MaintenancePlan" or value["operation_type"] != "UPDATE":
        raise ValueError("Unsupported maintenance plan operation")
    identifier = normalize_uuid(value["target_id"])
    _exact(value["business_key"], {"plan_code"})
    before, after = _plan_record(value["before"]), _plan_record(value["after"])
    if identifier != before["maintenance_plan_id"] or identifier != after["maintenance_plan_id"]:
        raise ValueError("Snapshot maintenance plan IDs disagree")
    if value["business_key"]["plan_code"] != before["plan_code"]:
        raise ValueError("Snapshot maintenance plan business key disagrees")
    for field in {"plan_code", "equipment_id"}:
        if before[field] != after[field]:
            raise ValueError("Maintenance plan immutable field changed")
    expected = _version(value["expected_version"])
    if before["version"] != expected or after["version"] != expected + 1:
        raise ValueError("Snapshot versions disagree")
    if all(before[field] == after[field] for field in PLAN_PATCH_FIELDS):
        raise ValueError("Maintenance plan update must change a business value")
    return {
        "target_type": "MaintenancePlan",
        "target_id": identifier,
        "business_key": {"plan_code": before["plan_code"]},
        "operation_type": "UPDATE",
        "before": before,
        "after": after,
        "expected_version": expected,
    }


def _create_target(value, target_type, record_validator, id_field, code_field):
    _exact(value, TARGET_FIELDS)
    if value["target_type"] != target_type or value["operation_type"] != "CREATE":
        raise ValueError("Unsupported CREATE target")
    if value["before"] is not None or value["expected_version"] is not None:
        raise ValueError("CREATE before and expected_version must be null")
    after = record_validator(value["after"])
    identifier = normalize_uuid(value["target_id"])
    _exact(value["business_key"], {code_field})
    if identifier != after[id_field] or value["business_key"][code_field] != after[code_field]:
        raise ValueError("CREATE identity or business key disagrees")
    if after["version"] != 1:
        raise ValueError("CREATE version must be 1")
    return {
        "target_type": target_type,
        "target_id": identifier,
        "business_key": {code_field: after[code_field]},
        "operation_type": "CREATE",
        "before": None,
        "after": after,
        "expected_version": None,
    }


def _new_target(values, fields, target_type, validator, id_field, code_field):
    _exact(values, fields)
    identifier = str(uuid4())
    return _create_target(
        {
            "target_type": target_type,
            "target_id": identifier,
            "business_key": {code_field: values[code_field]},
            "operation_type": "CREATE",
            "before": None,
            "after": {**values, id_field: identifier, "version": 1},
            "expected_version": None,
        },
        target_type,
        validator,
        id_field,
        code_field,
    )


def maintenance_plan_create_target(values):
    """Generate an ID once; callers retain this target through Prepare retries."""
    return _new_target(
        values,
        PLAN_FIELDS - {"maintenance_plan_id", "version"},
        "MaintenancePlan",
        _plan_record,
        "maintenance_plan_id",
        "plan_code",
    )


RECORD_FIELDS = {
    "maintenance_record_id",
    "record_code",
    "equipment_id",
    "performed_at",
    "result",
    "maintenance_plan_id",
    "version",
}


def _maintenance_record(value):
    _exact(value, RECORD_FIELDS)
    if type(value["record_code"]) is not str:
        raise ValueError("Maintenance record code must be text")
    if type(value["result"]) is not str or not value["result"].strip():
        raise ValueError("Maintenance result must be nonempty text")
    plan_id = value["maintenance_plan_id"]
    return {
        "maintenance_record_id": normalize_uuid(value["maintenance_record_id"]),
        "record_code": value["record_code"],
        "equipment_id": normalize_uuid(value["equipment_id"]),
        "performed_at": normalize_timestamp(value["performed_at"]),
        "result": value["result"],
        "maintenance_plan_id": normalize_uuid(plan_id) if plan_id is not None else None,
        "version": _version(value["version"]),
    }


def maintenance_record_create_target(values):
    """Build only a record proposal; do not infer state or plan changes."""
    if type(values) is not dict:
        raise ValueError("Maintenance record input must be an object")
    values = {"maintenance_plan_id": None, **values}
    return _new_target(
        values,
        RECORD_FIELDS - {"maintenance_record_id", "version"},
        "MaintenanceRecord",
        _maintenance_record,
        "maintenance_record_id",
        "record_code",
    )


OPERATION_FIELDS = {
    "production_operation_id",
    "operation_code",
    "process_id",
    "planned_status",
    "planned_start",
    "planned_end",
    "active",
    "version",
}
OPERATION_PATCH_FIELDS = {"planned_status", "planned_start", "planned_end"}


def _operation_record(value):
    with_assignments = type(value) is dict and "equipment_assignments" in value
    _exact(
        value,
        OPERATION_FIELDS | {"equipment_assignments"} if with_assignments else OPERATION_FIELDS,
    )
    if type(value["operation_code"]) is not str or type(value["active"]) is not bool:
        raise ValueError("Invalid production operation fields")
    if type(value["planned_status"]) is not str or value["planned_status"] not in {
        "PLANNED",
        "CANCELLED",
    }:
        raise ValueError("Invalid production operation planned status")
    start, end = (
        normalize_timestamp(value["planned_start"]),
        normalize_timestamp(value["planned_end"]),
    )
    if start >= end:
        raise ValueError("Production operation start must precede end")
    result = {
        "production_operation_id": normalize_uuid(value["production_operation_id"]),
        "operation_code": value["operation_code"],
        "process_id": normalize_uuid(value["process_id"]),
        "planned_status": value["planned_status"],
        "planned_start": start,
        "planned_end": end,
        "active": value["active"],
        "version": _version(value["version"]),
    }
    if with_assignments:
        rows = normalize_operation_assignments(
            result["production_operation_id"], value["equipment_assignments"]
        )
        if any(not row["active"] for row in rows):
            raise ValueError("Parent Snapshot collection must contain only active assignments")
        result["equipment_assignments"] = sorted(rows, key=lambda row: row["assignment_id"])
    return result


def production_operation_target(current, patch):
    """Build a schedule-only UPDATE; assignment replacements are unsupported."""
    if type(current) is not dict:
        raise ValueError("Current production operation must be a record")
    before = _operation_record(
        {key: value for key, value in current.items() if key not in {"created_at", "updated_at"}}
    )
    if "equipment_assignments" in before:
        raise ValueError("Use the assignment-aware builder for assignment collections")
    if type(patch) is not dict or not patch or not set(patch) <= OPERATION_PATCH_FIELDS:
        raise ValueError("Invalid production operation schedule patch")
    after = _operation_record({**before, **patch, "version": before["version"] + 1})
    return _operation_target(
        {
            "target_type": "ProductionOperation",
            "target_id": before["production_operation_id"],
            "business_key": {"operation_code": before["operation_code"]},
            "operation_type": "UPDATE",
            "before": before,
            "after": after,
            "expected_version": before["version"],
        }
    )


def _operation_target(value):
    _exact(value, TARGET_FIELDS)
    if value["target_type"] != "ProductionOperation" or value["operation_type"] != "UPDATE":
        raise ValueError("Unsupported production operation operation")
    identifier = normalize_uuid(value["target_id"])
    _exact(value["business_key"], {"operation_code"})
    before, after = _operation_record(value["before"]), _operation_record(value["after"])
    if (
        identifier != before["production_operation_id"]
        or identifier != after["production_operation_id"]
    ):
        raise ValueError("Snapshot production operation IDs disagree")
    if value["business_key"]["operation_code"] != before["operation_code"]:
        raise ValueError("Snapshot production operation business key disagrees")
    if any(before[field] != after[field] for field in {"operation_code", "process_id", "active"}):
        raise ValueError("Production operation immutable field changed")
    expected = _version(value["expected_version"])
    if before["version"] != expected or after["version"] != expected + 1:
        raise ValueError("Snapshot versions disagree")
    if ("equipment_assignments" in before) != ("equipment_assignments" in after):
        raise ValueError("Parent assignment collections must appear on both sides")
    if all(before[field] == after[field] for field in OPERATION_PATCH_FIELDS) and before.get(
        "equipment_assignments"
    ) == after.get("equipment_assignments"):
        raise ValueError("Production operation update must change a business value")
    return {
        "target_type": "ProductionOperation",
        "target_id": identifier,
        "business_key": {"operation_code": before["operation_code"]},
        "operation_type": "UPDATE",
        "before": before,
        "after": after,
        "expected_version": expected,
    }


def production_operation_assignment_targets(current, current_assignments, replacement, patch=None):
    """Build one parent plus every assignment diff from a trusted consistent read."""
    if type(current) is not dict:
        raise ValueError("Current production operation must be a record")
    before = _operation_record(
        {key: value for key, value in current.items() if key not in {"created_at", "updated_at"}}
    )
    if "equipment_assignments" in before:
        raise ValueError("Supply assignment rows separately from the parent row")
    changes = {} if patch is None else patch
    if (
        type(changes) is not dict
        or not set(changes) <= OPERATION_PATCH_FIELDS
        or (patch is not None and not patch)
    ):
        raise ValueError("Invalid production operation schedule patch")
    after = _operation_record({**before, **changes, "version": before["version"] + 1})
    if patch is not None and all(before[field] == after[field] for field in OPERATION_PATCH_FIELDS):
        raise ValueError("Schedule patch must change a business value")
    rows = normalize_operation_assignments(before["production_operation_id"], current_assignments)
    diffs = replacement_assignment_targets(before["production_operation_id"], rows, replacement)
    final = {row["assignment_id"]: row for row in rows if row["active"]}
    for target in diffs:
        final.pop(target["target_id"], None)
        if target["after"]["active"]:
            final[target["target_id"]] = target["after"]
    before["equipment_assignments"] = sorted(
        [row for row in rows if row["active"]], key=lambda row: row["assignment_id"]
    )
    after["equipment_assignments"] = sorted(final.values(), key=lambda row: row["assignment_id"])
    parent = _operation_target(
        {
            "target_type": "ProductionOperation",
            "target_id": before["production_operation_id"],
            "business_key": {"operation_code": before["operation_code"]},
            "operation_type": "UPDATE",
            "before": before,
            "after": after,
            "expected_version": before["version"],
        }
    )
    return [parent, *diffs]


def _validate_production_assignments(targets):
    parents = {
        target["target_id"]: target
        for target in targets
        if target["target_type"] == "ProductionOperation"
    }
    children = {}
    for target in targets:
        if target["target_type"] == "ProductionOperationEquipmentAssignment":
            operation_id = target["after"]["production_operation_id"]
            if (
                operation_id not in parents
                or "equipment_assignments" not in parents[operation_id]["before"]
            ):
                raise ValueError(
                    "Assignment Target requires a parent with fixed active collections"
                )
            children.setdefault(operation_id, []).append(target)
    all_source_ids, created_ids = set(), set()
    for operation_id, parent in parents.items():
        if "equipment_assignments" not in parent["before"]:
            continue
        before = {row["assignment_id"]: row for row in parent["before"]["equipment_assignments"]}
        source = list(before.values())
        diffs = children.get(operation_id, [])
        for target in diffs:
            old = target["before"]
            if old is not None:
                if old["active"]:
                    if before.get(target["target_id"]) != old:
                        raise ValueError("Assignment before differs from parent collection")
                else:
                    source.append(old)
        normalized_source = normalize_operation_assignments(operation_id, source)
        source_ids = {row["assignment_id"] for row in normalized_source}
        if all_source_ids & source_ids:
            raise ValueError("Assignment source ID appears under multiple parents")
        all_source_ids.update(source_ids)
        source_keys = {(row["equipment_id"], row["effective_from"]) for row in normalized_source}
        final = dict(before)
        for target in diffs:
            if target["operation_type"] == "CREATE":
                created_ids.add(target["target_id"])
            if target["operation_type"] == "CREATE" and (
                target["target_id"] in source_ids
                or (target["after"]["equipment_id"], target["after"]["effective_from"])
                in source_keys
            ):
                raise ValueError("Assignment CREATE conflicts with fixed source rows")
            final.pop(target["target_id"], None)
            if target["after"]["active"]:
                final[target["target_id"]] = target["after"]
        expected = sorted(final.values(), key=lambda row: row["assignment_id"])
        if expected != parent["after"]["equipment_assignments"]:
            raise ValueError("Assignment diff does not reproduce parent after collection")
    if created_ids & all_source_ids:
        raise ValueError("Assignment CREATE ID conflicts with another parent's source")


def _target(value):
    _exact(value, TARGET_FIELDS)
    if value["target_type"] == "EquipmentState":
        return _state_target(value)
    if value["target_type"] == "MaintenancePlan":
        return _plan_target(value)
    if value["target_type"] == "MaintenanceRecord":
        return _create_target(
            value, "MaintenanceRecord", _maintenance_record, "maintenance_record_id", "record_code"
        )
    if value["target_type"] == "ProductionOperation":
        return _operation_target(value)
    if value["target_type"] == "ProductionOperationEquipmentAssignment":
        return validate_assignment_target(value)
    if value["target_type"] == "DependencyRelation":
        return validate_relation_target(value)
    raise ValueError("Unsupported Snapshot target category")


def _snapshot(value):
    _exact(value, ROOT_FIELDS)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported Snapshot schema version")
    if type(value["requester_id"]) is not str or not value["requester_id"].strip():
        raise ValueError("Snapshot requester is required")
    if type(value["targets"]) is not list or not value["targets"]:
        raise ValueError("Snapshot requires at least one target")
    targets = [_target(target) for target in value["targets"]]
    if len({CATEGORIES[target["target_type"]] for target in targets}) != 1:
        raise ValueError("Snapshot must contain one business category")
    identities = [(target["target_type"], target["target_id"]) for target in targets]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate Snapshot target")
    business_keys = [
        (target["target_type"], canonical_json(target["business_key"])) for target in targets
    ]
    if len(set(business_keys)) != len(business_keys):
        raise ValueError("Duplicate Snapshot business key")
    _validate_production_assignments(targets)
    targets.sort(key=lambda target: (target["target_type"], target["target_id"]))
    supersedes = value["supersedes_update_request_id"]
    return {
        "schema_version": 1,
        "requester_id": value["requester_id"],
        "supersedes_update_request_id": normalize_uuid(supersedes)
        if supersedes is not None
        else None,
        "targets": targets,
    }


@dataclass(frozen=True)
class CanonicalSnapshot:
    canonical_text: str
    snapshot_hash: str

    def __post_init__(self):
        if type(self.canonical_text) is not str:
            raise ValueError("Canonical Snapshot must be text")
        normalized = _snapshot(strict_json(self.canonical_text))
        if canonical_json(normalized) != self.canonical_text:
            raise ValueError("Snapshot text is not canonical")
        if type(self.snapshot_hash) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.snapshot_hash
        ):
            raise ValueError("Invalid Snapshot hash")
        calculated = hashlib.sha256(self.canonical_text.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(calculated, self.snapshot_hash):
            raise ValueError("Snapshot hash mismatch")

    @property
    def data(self):
        # Each call returns a new object; callers cannot modify the saved Snapshot.
        return strict_json(self.canonical_text)


def build_equipment_state_snapshot(context, targets, supersedes_update_request_id=None):
    return _build_snapshot(context, targets, supersedes_update_request_id, {"EquipmentState"})


def build_maintenance_plan_snapshot(context, targets, supersedes_update_request_id=None):
    return _build_snapshot(context, targets, supersedes_update_request_id, {"MaintenancePlan"})


def build_maintenance_snapshot(context, targets, supersedes_update_request_id=None):
    return _build_snapshot(
        context, targets, supersedes_update_request_id, {"MaintenancePlan", "MaintenanceRecord"}
    )


def build_production_operation_snapshot(context, targets, supersedes_update_request_id=None):
    return _build_snapshot(
        context,
        targets,
        supersedes_update_request_id,
        {"ProductionOperation", "ProductionOperationEquipmentAssignment"},
    )


def build_dependency_relation_snapshot(context, targets, supersedes_update_request_id=None):
    return _build_snapshot(context, targets, supersedes_update_request_id, {"DependencyRelation"})


def _build_snapshot(context, targets, supersedes_update_request_id, target_types):
    if not isinstance(context, ExecutionContext):
        raise ValueError("Trusted execution context is required")
    value = _snapshot(
        {
            "schema_version": 1,
            "requester_id": context.authenticated_user_id,
            "supersedes_update_request_id": supersedes_update_request_id,
            "targets": targets,
        }
    )
    if any(target["target_type"] not in target_types for target in value["targets"]):
        raise ValueError("Snapshot builder category mismatch")
    text = canonical_json(value)
    return CanonicalSnapshot(text, hashlib.sha256(text.encode("utf-8")).hexdigest())
