from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from linescope.canonical import canonical_hash, canonical_json
from linescope.execution import ExecutionContext
from linescope.snapshot import (
    MAX_VERSION,
    CanonicalSnapshot,
    build_production_operation_snapshot,
    maintenance_plan_create_target,
    production_operation_target,
)


def current(identifier=1):
    return {
        "production_operation_id": UUID(int=identifier),
        "operation_code": f"OP-{identifier}",
        "process_id": UUID(int=20),
        "planned_status": "PLANNED",
        "planned_start": "2026-10-09T09:00:00+09:00",
        "planned_end": "2026-10-10T09:00:00+09:00",
        "active": True,
        "version": 5,
        "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 8, tzinfo=timezone.utc),
    }


def target(identifier=1):
    return production_operation_target(current(identifier), {"planned_status": "CANCELLED"})


def snapshot(*targets):
    return build_production_operation_snapshot(
        ExecutionContext("production1", "production", uuid4()), list(targets) or [target()]
    )


def reload(payload):
    return CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))


def test_schedule_snapshot_has_full_business_values_and_parent_version():
    row = current()
    original = deepcopy(row)
    proposal = production_operation_target(row, {"planned_status": "CANCELLED"})
    assert row == original
    assert proposal["business_key"] == {"operation_code": "OP-1"}
    assert proposal["expected_version"] == 5
    assert proposal["after"] == {**proposal["before"], "planned_status": "CANCELLED", "version": 6}
    assert proposal["before"] == {
        "production_operation_id": str(UUID(int=1)),
        "operation_code": "OP-1",
        "process_id": str(UUID(int=20)),
        "planned_status": "PLANNED",
        "planned_start": "2026-10-09T00:00:00.000000Z",
        "planned_end": "2026-10-10T00:00:00.000000Z",
        "active": True,
        "version": 5,
    }
    value = snapshot(proposal)
    assert reload(value.data) == value
    assert len(value.data["targets"]) == 1


def test_timezone_and_audit_changes_preserve_hash_but_business_changes_do_not():
    row = current()
    row["planned_start"] = "2026-10-09T00:00:00Z"
    row["planned_end"] = "2026-10-10T00:00:00Z"
    row["created_at"] = "audit value outside hash"
    del row["updated_at"]
    assert snapshot(production_operation_target(row, {"planned_status": "CANCELLED"})) == snapshot()
    for patch in [
        {"planned_start": "2026-10-08T00:00:00Z"},
        {"planned_end": "2026-10-11T00:00:00Z"},
    ]:
        assert (
            snapshot(production_operation_target(current(), patch)).snapshot_hash
            != snapshot().snapshot_hash
        )


@pytest.mark.parametrize("before,after", [("PLANNED", "CANCELLED"), ("CANCELLED", "PLANNED")])
def test_both_planned_status_transitions_are_supported(before, after):
    row = current()
    row["planned_status"] = before
    assert (
        production_operation_target(row, {"planned_status": after})["after"]["planned_status"]
        == after
    )


def test_multi_field_patch_validates_final_interval_and_increments_version_once():
    patch = {
        "planned_status": "CANCELLED",
        "planned_start": "2026-10-11T00:00:00Z",
        "planned_end": "2026-10-12T00:00:00Z",
    }
    proposal = production_operation_target(current(), patch)
    assert proposal["after"]["version"] == 6
    assert proposal["after"]["planned_start"] == "2026-10-11T00:00:00.000000Z"


@pytest.mark.parametrize(
    "patch",
    [
        {},
        None,
        {"version": 9},
        {"operation_code": "new"},
        {"process_id": str(UUID(int=21))},
        {"active": False},
        {"production_operation_id": str(UUID(int=2))},
        {"equipment_ids": []},
        {"assignment_replacement": {}},
        {"planned_status": "RUNNING"},
        {"planned_status": None},
        {"planned_start": None},
        {"planned_end": "2026-10-10T00:00:00"},
        {"planned_start": "2026-10-10T00:00:00Z"},
        {"planned_end": "2026-10-08T00:00:00Z"},
        {"planned_status": "PLANNED"},
        {"planned_start": "2026-10-09T00:00:00Z"},
    ],
)
def test_invalid_and_noop_patches_fail_closed(patch):
    with pytest.raises(ValueError):
        production_operation_target(current(), patch)


@pytest.mark.parametrize(
    "field,value",
    [
        ("active", 1),
        ("active", None),
        ("operation_code", None),
        ("process_id", "bad"),
        ("version", True),
        ("version", MAX_VERSION),
        ("planned_status", "UNKNOWN"),
        ("planned_start", "2026-10-09T00:00:00.0000001Z"),
    ],
)
def test_invalid_current_values_rejected(field, value):
    row = current()
    row[field] = value
    with pytest.raises(ValueError):
        production_operation_target(row, {"planned_status": "CANCELLED"})


def test_missing_business_fields_and_unknown_source_fields_rejected():
    row = current()
    for field in set(row) - {"created_at", "updated_at"}:
        incomplete = {key: value for key, value in row.items() if key != field}
        with pytest.raises(ValueError):
            production_operation_target(incomplete, {"planned_status": "CANCELLED"})
    row["equipment_id"] = str(UUID(int=30))
    with pytest.raises(ValueError):
        production_operation_target(row, {"planned_status": "CANCELLED"})


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "code",
        "process",
        "active",
        "key",
        "expected",
        "version",
        "noop",
        "interval",
        "audit",
        "create",
        "assignment",
    ],
)
def test_saved_schema_tampering_rejected_even_with_recomputed_hash(change):
    payload = snapshot().data
    item = payload["targets"][0]
    if change == "id":
        item["after"]["production_operation_id"] = str(UUID(int=2))
    elif change == "code":
        item["after"]["operation_code"] = "other"
    elif change == "process":
        item["after"]["process_id"] = str(UUID(int=21))
    elif change == "active":
        item["after"]["active"] = False
    elif change == "key":
        item["business_key"]["operation_code"] = "other"
    elif change == "expected":
        item["expected_version"] = 4
    elif change == "version":
        item["after"]["version"] = 7
    elif change == "noop":
        item["after"]["planned_status"] = "PLANNED"
    elif change == "interval":
        item["after"]["planned_end"] = item["after"]["planned_start"]
    elif change == "audit":
        item["after"]["updated_at"] = "2026-10-09T00:00:00Z"
    elif change == "create":
        item["operation_type"] = "CREATE"
    elif change == "assignment":
        item["target_type"] = "ProductionOperationEquipmentAssignment"
    with pytest.raises(ValueError):
        reload(payload)


def test_order_duplicates_and_category_boundaries():
    assert snapshot(target(2), target(1)) == snapshot(target(1), target(2))
    with pytest.raises(ValueError, match="Duplicate"):
        snapshot(target(), target())
    maintenance = maintenance_plan_create_target(
        {
            "plan_code": "PLAN",
            "equipment_id": str(UUID(int=30)),
            "planned_start": "2026-10-09T00:00:00Z",
            "planned_end": "2026-10-10T00:00:00Z",
            "plan_status": "PLANNED",
        }
    )
    with pytest.raises(ValueError, match="one business category"):
        snapshot(target(), maintenance)
    with pytest.raises(ValueError, match="category mismatch"):
        snapshot(maintenance)
    payload = snapshot().data
    payload["targets"].append(maintenance)
    with pytest.raises(ValueError, match="one business category"):
        reload(payload)
