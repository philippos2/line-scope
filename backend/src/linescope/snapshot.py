"""Canonical Snapshot v1 for equipment-state and maintenance proposals.

This pure construction/validation layer does not authorize, persist or execute
updates. Prepare must supply current PostgreSQL state and check permissions.
Other target categories are rejected until their schemas are implemented.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from uuid import uuid4

from .canonical import canonical_json, normalize_timestamp, normalize_uuid, strict_json
from .execution import ExecutionContext

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
