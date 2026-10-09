from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from linescope.canonical import canonical_hash, canonical_json
from linescope.execution import ExecutionContext
from linescope.snapshot import (
    CanonicalSnapshot,
    build_maintenance_snapshot,
    maintenance_plan_create_target,
    maintenance_plan_target,
    maintenance_record_create_target,
)


def plan():
    return {
        "plan_code": "PLAN-NEW",
        "equipment_id": str(UUID(int=20)),
        "planned_start": "2026-10-09T09:00:00+09:00",
        "planned_end": "2026-10-10T09:00:00+09:00",
        "plan_status": "PLANNED",
    }


def record():
    return {
        "record_code": "RECORD-NEW",
        "equipment_id": str(UUID(int=20)),
        "performed_at": "2026-10-09T09:00:00+09:00",
        "result": "  Inspected: no issue.\n2026-10-09T09:00:00+09:00  ",
    }


def snapshot(*targets):
    return build_maintenance_snapshot(
        ExecutionContext("maintenance1", "maintenance", uuid4()), list(targets)
    )


def reload(payload):
    return CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))


@pytest.mark.parametrize(
    "factory,input_factory,id_field,code_field",
    [
        (maintenance_plan_create_target, plan, "maintenance_plan_id", "plan_code"),
        (maintenance_record_create_target, record, "maintenance_record_id", "record_code"),
    ],
)
def test_server_generated_id_fixed_in_target_and_reload(
    factory, input_factory, id_field, code_field
):
    values = input_factory()
    original = deepcopy(values)
    proposal = factory(values)
    assert values == original
    assert UUID(proposal["target_id"]).version == 4
    assert proposal["after"][id_field] == proposal["target_id"]
    assert proposal["before"] is None
    assert proposal["expected_version"] is None
    assert proposal["after"]["version"] == 1
    assert proposal["business_key"] == {code_field: values[code_field]}
    first = snapshot(proposal)
    assert reload(first.data) == first == snapshot(proposal)
    assert factory(values)["target_id"] != proposal["target_id"]


def test_same_generated_id_timezone_and_nullable_normalization(monkeypatch):
    monkeypatch.setattr("linescope.snapshot.uuid4", lambda: UUID(int=40))
    values = record()
    first = maintenance_record_create_target(values)
    values["performed_at"] = "2026-10-09T00:00:00.000000Z"
    values["maintenance_plan_id"] = None
    assert snapshot(first) == snapshot(maintenance_record_create_target(values))
    assert first["after"]["result"] == record()["result"]
    assert first["after"]["maintenance_plan_id"] is None
    values["result"] = "Different inspection"
    assert (
        snapshot(first).snapshot_hash
        != snapshot(maintenance_record_create_target(values)).snapshot_hash
    )


def test_record_only_proposal_has_no_state_or_plan_side_effect_target():
    values = record()
    values["maintenance_plan_id"] = str(UUID(int=30))
    proposal = maintenance_record_create_target(values)
    payload = snapshot(proposal).data
    assert len(payload["targets"]) == 1
    assert payload["targets"][0]["target_type"] == "MaintenanceRecord"
    assert proposal["after"]["maintenance_plan_id"] == str(UUID(int=30))


def test_maintenance_category_allows_plan_create_update_and_record_create():
    existing = {**plan(), "maintenance_plan_id": str(UUID(int=30)), "version": 4}
    existing["plan_code"] = "PLAN-EXISTING"
    update = maintenance_plan_target(existing, {"plan_status": "CANCELLED"})
    create = maintenance_plan_create_target(plan())
    result = maintenance_record_create_target(record())
    value = snapshot(result, create, update)
    assert value == snapshot(update, result, create) == reload(value.data)
    assert {item["target_type"] for item in value.data["targets"]} == {
        "MaintenancePlan",
        "MaintenanceRecord",
    }


@pytest.mark.parametrize(
    "factory,input_factory",
    [
        (maintenance_plan_create_target, plan),
        (maintenance_record_create_target, record),
    ],
)
def test_missing_required_and_unknown_input_fields_rejected(factory, input_factory):
    for field in input_factory():
        values = input_factory()
        del values[field]
        with pytest.raises(ValueError):
            factory(values)
    for field in [
        "version",
        "target_id",
        "maintenance_plan_id"
        if factory is maintenance_plan_create_target
        else "maintenance_record_id",
        "updated_at",
    ]:
        values = input_factory()
        values[field] = str(UUID(int=50))
        with pytest.raises(ValueError):
            factory(values)
    with pytest.raises(ValueError):
        factory(None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("result", ""),
        ("result", " \n\t "),
        ("result", None),
        ("result", 1),
        ("record_code", None),
        ("equipment_id", None),
        ("maintenance_plan_id", "bad"),
        ("performed_at", "2026-10-09T00:00:00"),
        ("performed_at", None),
    ],
)
def test_invalid_record_values_rejected(field, value):
    values = record()
    values[field] = value
    with pytest.raises(ValueError):
        maintenance_record_create_target(values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("planned_end", "2026-10-09T00:00:00Z"),
        ("plan_status", "COMPLETED"),
        ("plan_status", None),
        ("planned_start", None),
        ("plan_code", None),
        ("equipment_id", "bad"),
    ],
)
def test_invalid_plan_values_rejected(field, value):
    values = plan()
    values[field] = value
    with pytest.raises(ValueError):
        maintenance_plan_create_target(values)


@pytest.mark.parametrize(
    "factory,input_factory",
    [
        (maintenance_plan_create_target, plan),
        (maintenance_record_create_target, record),
    ],
)
@pytest.mark.parametrize("change", ["before", "expected", "version", "id", "key", "operation"])
def test_create_schema_tampering_rejected_even_with_new_hash(factory, input_factory, change):
    payload = snapshot(factory(input_factory())).data
    item = payload["targets"][0]
    if change == "before":
        item["before"] = {}
    elif change == "expected":
        item["expected_version"] = 1
    elif change == "version":
        item["after"]["version"] = 2
    elif change == "id":
        item["target_id"] = str(UUID(int=70))
    elif change == "key":
        key = next(iter(item["business_key"]))
        item["business_key"][key] = "other"
    else:
        item["operation_type"] = "DISABLE"
    with pytest.raises(ValueError):
        reload(payload)


def test_missing_explicit_null_in_saved_record_rejected():
    payload = snapshot(maintenance_record_create_target(record())).data
    del payload["targets"][0]["after"]["maintenance_plan_id"]
    with pytest.raises(ValueError):
        reload(payload)


@pytest.mark.parametrize(
    "factory,input_factory",
    [
        (maintenance_plan_create_target, plan),
        (maintenance_record_create_target, record),
    ],
)
def test_duplicate_business_keys_rejected_with_distinct_generated_ids(factory, input_factory):
    first, second = factory(input_factory()), factory(input_factory())
    assert first["target_id"] != second["target_id"]
    with pytest.raises(ValueError, match="Duplicate Snapshot business key"):
        snapshot(first, second)
    payload = snapshot(first).data
    payload["targets"].append(second)
    with pytest.raises(ValueError, match="Duplicate Snapshot business key"):
        reload(payload)
