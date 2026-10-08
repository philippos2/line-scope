from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from linescope.canonical import canonical_hash, canonical_json
from linescope.execution import ExecutionContext
from linescope.snapshot import (
    MAX_VERSION,
    CanonicalSnapshot,
    build_equipment_state_snapshot,
    equipment_state_target,
)


def context(user="floor1", role="floor"):
    return ExecutionContext(user, role, uuid4())


def target(identifier=1, before="RUNNING", after="STOPPED", version=3):
    return equipment_state_target(
        {
            "equipment_id": str(UUID(int=identifier)),
            "state_code": before,
            "version": version,
            "updated_at": datetime(2026, 10, 9, tzinfo=timezone.utc),
        },
        after,
    )


def test_target_uses_current_state_version_and_excludes_timestamp():
    value = target()
    assert value == {
        "target_type": "EquipmentState",
        "target_id": str(UUID(int=1)),
        "business_key": {"equipment_id": str(UUID(int=1))},
        "operation_type": "UPDATE",
        "before": {"equipment_id": str(UUID(int=1)), "state_code": "RUNNING", "version": 3},
        "after": {"equipment_id": str(UUID(int=1)), "state_code": "STOPPED", "version": 4},
        "expected_version": 3,
    }


@pytest.mark.parametrize("before", ["RUNNING", "STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"])
@pytest.mark.parametrize("after", ["RUNNING", "STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"])
def test_state_transitions_allow_all_changes_but_reject_noop(before, after):
    if before == after:
        with pytest.raises(ValueError):
            target(before=before, after=after)
    else:
        assert target(before=before, after=after)["after"]["state_code"] == after


@pytest.mark.parametrize("version", [0, -1, True, 1.0, None, MAX_VERSION])
def test_invalid_and_overflow_versions_rejected(version):
    with pytest.raises(ValueError):
        target(version=version)


@pytest.mark.parametrize(
    "current,state",
    [
        ({"equipment_id": str(UUID(int=1)), "state_code": "RUNNING"}, "STOPPED"),
        ({"equipment_id": str(UUID(int=1)), "state_code": "BROKEN", "version": 1}, "STOPPED"),
        ({"equipment_id": str(UUID(int=1)), "state_code": "RUNNING", "version": 1}, None),
        ({"equipment_id": str(UUID(int=1)), "state_code": "RUNNING", "version": 1}, "MAINTENANCE"),
        ({"equipment_id": "invalid", "state_code": "RUNNING", "version": 1}, "STOPPED"),
        (
            {
                "equipment_id": str(UUID(int=1)),
                "state_code": "RUNNING",
                "version": 1,
                "equipment_code": "EQ1",
            },
            "STOPPED",
        ),
    ],
)
def test_incomplete_or_wrong_source_record_rejected(current, state):
    with pytest.raises(ValueError):
        equipment_state_target(current, state)


def test_targets_are_sorted_and_snapshot_is_defensively_immutable():
    inputs = [target(2), target(1)]
    snapshot = build_equipment_state_snapshot(context(), inputs)
    assert [value["target_id"] for value in snapshot.data["targets"]] == [
        str(UUID(int=1)),
        str(UUID(int=2)),
    ]
    assert snapshot.data["supersedes_update_request_id"] is None
    inputs[0]["after"]["state_code"] = "UNKNOWN"
    view = snapshot.data
    view["targets"][0]["after"]["state_code"] = "UNKNOWN"
    assert all(value["after"]["state_code"] == "STOPPED" for value in snapshot.data["targets"])
    assert snapshot.snapshot_hash == canonical_hash(snapshot.data)


def test_request_id_role_audit_time_and_order_do_not_change_hash():
    first = build_equipment_state_snapshot(context(), [target(2), target(1)])
    second = build_equipment_state_snapshot(context(role="manager"), [target(1), target(2)])
    assert first == second
    changed_audit = equipment_state_target(
        {
            "equipment_id": str(UUID(int=1)),
            "state_code": "RUNNING",
            "version": 3,
            "updated_at": "a different audit time, outside hash",
        },
        "STOPPED",
    )
    assert first == build_equipment_state_snapshot(context(), [changed_audit, target(2)])


def test_requester_business_version_and_supersedes_are_hash_inputs():
    original = build_equipment_state_snapshot(context(), [target()])
    alternatives = [
        build_equipment_state_snapshot(context(user="other"), [target()]),
        build_equipment_state_snapshot(context(), [target(after="UNKNOWN")]),
        build_equipment_state_snapshot(context(), [target(version=4)]),
        build_equipment_state_snapshot(context(), [target()], str(UUID(int=9))),
    ]
    assert all(value.snapshot_hash != original.snapshot_hash for value in alternatives)


def test_uuid_case_and_nested_key_order_normalize_before_hash():
    value = target()
    identifier = "ABCDEFAB-1234-5678-ABCD-123456789ABC"
    value["target_id"] = identifier
    value["business_key"]["equipment_id"] = identifier
    for field in ["before", "after"]:
        value[field]["equipment_id"] = identifier
    other = deepcopy(value)
    other["target_id"] = identifier.lower()
    other["business_key"]["equipment_id"] = identifier.lower()
    for field in ["before", "after"]:
        other[field] = dict(reversed(list(other[field].items())))
        other[field]["equipment_id"] = identifier.lower()
    assert build_equipment_state_snapshot(context(), [value]) == build_equipment_state_snapshot(
        context(), [other]
    )


def test_duplicate_target_and_untrusted_context_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        build_equipment_state_snapshot(context(), [target(), target()])
    for identity in [None, {"authenticated_user_id": "forged", "role": "manager"}]:
        with pytest.raises(ValueError):
            build_equipment_state_snapshot(identity, [target()])


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("requester_id", ""),
        ("targets", []),
        ("targets", None),
        ("supersedes_update_request_id", "invalid"),
    ],
)
def test_invalid_root_schema_rejected_even_with_matching_hash(field, value):
    payload = build_equipment_state_snapshot(context(), [target()]).data
    payload[field] = value
    with pytest.raises(ValueError):
        CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))


@pytest.mark.parametrize(
    "change",
    [
        "expected",
        "after_version",
        "before_version",
        "target_id",
        "business_key",
        "before_id",
        "after_id",
        "state",
        "audit",
        "unknown_field",
        "create",
        "other_category",
        "missing_null",
    ],
)
def test_tampered_schema_rejected_even_if_hash_is_recomputed(change):
    payload = build_equipment_state_snapshot(context(), [target()]).data
    item = payload["targets"][0]
    if change == "expected":
        item["expected_version"] = 2
    elif change == "after_version":
        item["after"]["version"] = 5
    elif change == "before_version":
        item["before"]["version"] = 2
    elif change == "target_id":
        item["target_id"] = str(UUID(int=9))
    elif change == "business_key":
        item["business_key"]["equipment_id"] = str(UUID(int=9))
    elif change == "before_id":
        item["before"]["equipment_id"] = str(UUID(int=9))
    elif change == "after_id":
        item["after"]["equipment_id"] = str(UUID(int=9))
    elif change == "state":
        item["after"]["state_code"] = "DEGRADED"
    elif change == "audit":
        item["after"]["updated_at"] = "2026-10-09T00:00:00Z"
    elif change == "unknown_field":
        payload["request_id"] = str(uuid4())
    elif change == "create":
        item["operation_type"] = "CREATE"
    elif change == "other_category":
        item["target_type"] = "MaintenancePlan"
    elif change == "missing_null":
        del payload["supersedes_update_request_id"]
    with pytest.raises(ValueError):
        CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))


def test_noncanonical_text_and_wrong_hash_rejected():
    snapshot = build_equipment_state_snapshot(context(), [target(1), target(2)])
    with pytest.raises(ValueError):
        CanonicalSnapshot(" " + snapshot.canonical_text, snapshot.snapshot_hash)
    payload = snapshot.data
    payload["targets"].reverse()
    with pytest.raises(ValueError):
        CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))
    for checksum in ["0" * 64, "X" * 64, snapshot.snapshot_hash.upper(), None]:
        with pytest.raises(ValueError):
            CanonicalSnapshot(snapshot.canonical_text, checksum)
    assert CanonicalSnapshot(snapshot.canonical_text, snapshot.snapshot_hash) == snapshot
