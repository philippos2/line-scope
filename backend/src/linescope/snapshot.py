"""Canonical Snapshot v1 for equipment-state UPDATEs.

This pure construction/validation layer does not authorize, persist or execute
updates. Prepare must supply current PostgreSQL state and check permissions.
Other target categories are rejected until their schemas are implemented.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass

from .canonical import canonical_json, normalize_uuid, strict_json
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


def _target(value):
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


def _snapshot(value):
    _exact(value, ROOT_FIELDS)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported Snapshot schema version")
    if type(value["requester_id"]) is not str or not value["requester_id"].strip():
        raise ValueError("Snapshot requester is required")
    if type(value["targets"]) is not list or not value["targets"]:
        raise ValueError("Snapshot requires at least one target")
    targets = [_target(target) for target in value["targets"]]
    identities = [(target["target_type"], target["target_id"]) for target in targets]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate Snapshot target")
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
    text = canonical_json(value)
    return CanonicalSnapshot(text, hashlib.sha256(text.encode("utf-8")).hexdigest())
