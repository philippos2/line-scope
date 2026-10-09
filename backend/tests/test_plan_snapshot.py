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
    build_maintenance_plan_snapshot,
    equipment_state_target,
    maintenance_plan_target,
)


def context():
    return ExecutionContext("maintenance1", "maintenance", uuid4())


def current(identifier=1):
    return {
        "maintenance_plan_id": UUID(int=identifier),
        "plan_code": f"PLAN-{identifier}",
        "equipment_id": UUID(int=10),
        "planned_start": datetime(2026, 10, 9, tzinfo=timezone.utc),
        "planned_end": datetime(2026, 10, 10, tzinfo=timezone.utc),
        "plan_status": "PLANNED",
        "version": 3,
    }


def target(identifier=1):
    return maintenance_plan_target(current(identifier), {"plan_status": "CANCELLED"})


def snapshot(*targets):
    return build_maintenance_plan_snapshot(context(), list(targets) or [target()])


def reload(payload):
    return CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))


def test_full_business_record_and_derived_version():
    row = current()
    proposal = maintenance_plan_target(row, {"plan_status": "CANCELLED"})
    assert row == current()
    assert proposal["business_key"] == {"plan_code": "PLAN-1"}
    assert proposal["expected_version"] == 3
    assert proposal["before"]["version"] == 3
    assert proposal["after"] == {**proposal["before"], "plan_status": "CANCELLED", "version": 4}
    assert proposal["before"]["planned_start"] == "2026-10-09T00:00:00.000000Z"
    assert proposal["before"]["equipment_id"] == str(UUID(int=10))
    value = snapshot(proposal)
    assert reload(value.data) == value


def test_timezone_and_uuid_representations_do_not_change_hash():
    row = current()
    row["planned_start"] = "2026-10-09T09:00:00+09:00"
    row["planned_end"] = "2026-10-10T09:00:00+09:00"
    row["equipment_id"] = str(row["equipment_id"])
    assert snapshot(maintenance_plan_target(row, {"plan_status": "CANCELLED"})) == snapshot()


@pytest.mark.parametrize(
    "patch",
    [
        {},
        None,
        {"version": 8},
        {"equipment_id": str(UUID(int=11))},
        {"plan_code": "other"},
        {"maintenance_plan_id": str(UUID(int=2))},
        {"plan_status": "COMPLETED"},
        {"plan_status": None},
        {"plan_status": True},
        {"planned_start": None},
        {"planned_end": "2026-10-10T00:00:00"},
        {"planned_end": "2026-10-10T00:00:00.0000001Z"},
        {"planned_start": "2026-10-10T00:00:00Z"},
        {"planned_end": "2026-10-08T00:00:00Z"},
        {"plan_status": "PLANNED"},
        {"planned_start": "2026-10-09T09:00:00+09:00"},
    ],
)
def test_invalid_or_noop_patch_rejected(patch):
    with pytest.raises(ValueError):
        maintenance_plan_target(current(), patch)


def test_partial_patch_validates_final_interval_not_intermediate_values():
    value = maintenance_plan_target(
        current(),
        {
            "planned_start": "2026-10-11T00:00:00Z",
            "planned_end": "2026-10-12T00:00:00Z",
        },
    )
    assert value["after"]["planned_start"] == "2026-10-11T00:00:00.000000Z"
    assert snapshot(value).snapshot_hash != snapshot().snapshot_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_code", None),
        ("equipment_id", "invalid"),
        ("version", True),
        ("version", MAX_VERSION),
        ("planned_start", "invalid"),
        ("plan_status", "UNKNOWN"),
    ],
)
def test_invalid_source_row_rejected(field, value):
    row = current()
    row[field] = value
    with pytest.raises(ValueError):
        maintenance_plan_target(row, {"plan_status": "CANCELLED"})


def test_missing_and_unknown_source_fields_rejected():
    for field in current():
        row = current()
        del row[field]
        with pytest.raises(ValueError):
            maintenance_plan_target(row, {"plan_status": "CANCELLED"})
    row = current()
    row["updated_at"] = "2026-10-09T00:00:00Z"
    with pytest.raises(ValueError):
        maintenance_plan_target(row, {"plan_status": "CANCELLED"})


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "equipment",
        "code",
        "key",
        "expected",
        "version",
        "noop",
        "interval",
        "timezone",
        "missing",
        "extra",
        "create",
    ],
)
def test_saved_target_schema_tampering_rejected_with_recomputed_hash(change):
    payload = snapshot().data
    item = payload["targets"][0]
    if change == "id":
        item["after"]["maintenance_plan_id"] = str(UUID(int=2))
    elif change == "equipment":
        item["after"]["equipment_id"] = str(UUID(int=20))
    elif change == "code":
        item["after"]["plan_code"] = "other"
    elif change == "key":
        item["business_key"]["plan_code"] = "other"
    elif change == "expected":
        item["expected_version"] = 2
    elif change == "version":
        item["after"]["version"] = 5
    elif change == "noop":
        item["after"]["plan_status"] = "PLANNED"
    elif change == "interval":
        item["after"]["planned_end"] = item["after"]["planned_start"]
    elif change == "timezone":
        item["after"]["planned_start"] = "2026-10-09T09:00:00+09:00"
    elif change == "missing":
        del item["before"]["equipment_id"]
    elif change == "extra":
        item["after"]["updated_at"] = "2026-10-09T00:00:00Z"
    elif change == "create":
        item["operation_type"] = "CREATE"
    with pytest.raises(ValueError):
        reload(payload)


def test_multiple_targets_sort_duplicate_and_mixed_category_rejection():
    assert snapshot(target(2), target(1)) == snapshot(target(1), target(2))
    with pytest.raises(ValueError, match="Duplicate"):
        snapshot(target(), target())
    state = equipment_state_target(
        {"equipment_id": str(UUID(int=10)), "state_code": "RUNNING", "version": 1}, "STOPPED"
    )
    with pytest.raises(ValueError, match="one business category"):
        snapshot(target(), state)
    payload = snapshot().data
    payload["targets"].append(state)
    with pytest.raises(ValueError, match="one business category"):
        reload(payload)
    with pytest.raises(ValueError, match="category mismatch"):
        snapshot(state)
    with pytest.raises(ValueError, match="category mismatch"):
        build_equipment_state_snapshot(context(), [target()])


def test_business_changes_change_hash_and_payload_is_immutable():
    proposal = target()
    value = snapshot(proposal)
    changed = deepcopy(proposal)
    changed["after"]["planned_end"] = "2026-10-11T00:00:00.000000Z"
    assert snapshot(changed).snapshot_hash != value.snapshot_hash
    proposal["after"]["plan_status"] = "PLANNED"
    view = value.data
    view["targets"][0]["after"]["plan_status"] = "PLANNED"
    assert value.data["targets"][0]["after"]["plan_status"] == "CANCELLED"
