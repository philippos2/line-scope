from copy import deepcopy
from itertools import count
from uuid import UUID, uuid4

import pytest

from linescope.canonical import canonical_hash, canonical_json
from linescope.execution import ExecutionContext
from linescope.snapshot import (
    CanonicalSnapshot,
    build_production_operation_snapshot,
    production_operation_assignment_targets,
    production_operation_target,
)

E1, E2 = str(UUID(int=1)), str(UUID(int=2))


def time(hour):
    return f"2026-10-09T{hour:02d}:00:00.000000Z"


def operation(identifier=100):
    return {
        "production_operation_id": str(UUID(int=identifier)),
        "operation_code": f"OP-{identifier}",
        "process_id": str(UUID(int=200)),
        "planned_status": "PLANNED",
        "planned_start": time(0),
        "planned_end": time(10),
        "active": True,
        "version": 7,
    }


def row(identifier=10, equipment=E1, start=0, end=6, active=True, op=100, version=3):
    return {
        "assignment_id": str(UUID(int=identifier)),
        "production_operation_id": str(UUID(int=op)),
        "equipment_id": equipment,
        "effective_from": time(start),
        "effective_to": time(end) if end is not None else None,
        "active": active,
        "version": version,
    }


def replacement(equipment=E2, start=2, end=4):
    return {
        "effective_from": time(start),
        "effective_to": time(end) if end is not None else None,
        "equipment_ids": [equipment] if equipment is not None else [],
    }


def targets(rows=None, patch=None, op=100):
    return production_operation_assignment_targets(
        operation(op), [row(op=op)] if rows is None else rows, replacement(), patch
    )


def snapshot(values):
    return build_production_operation_snapshot(
        ExecutionContext("production1", "production", uuid4()), values
    )


def reload(payload):
    return CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))


def parent(payload):
    return next(
        target for target in payload["targets"] if target["target_type"] == "ProductionOperation"
    )


def test_assignment_only_update_fixes_full_active_collections_and_one_parent_increment():
    source = [row(), row(11, E1, 12, 14)]
    original = deepcopy(source)
    value = snapshot(targets(source))
    item = parent(value.data)
    assert source == original
    assert item["expected_version"] == 7
    assert item["after"]["version"] == 8
    assert item["before"]["planned_status"] == item["after"]["planned_status"] == "PLANNED"
    assert item["before"]["equipment_assignments"] == source
    unchanged = next(
        r
        for r in item["after"]["equipment_assignments"]
        if r["assignment_id"] == source[1]["assignment_id"]
    )
    assert unchanged == source[1]
    assert len(item["after"]["equipment_assignments"]) == 4
    assert value == reload(value.data)


def test_schedule_and_assignment_combination_increments_parent_once():
    value = snapshot(targets(patch={"planned_status": "CANCELLED", "planned_end": time(11)}))
    item = parent(value.data)
    assert item["after"]["version"] == 8
    assert item["after"]["planned_status"] == "CANCELLED"
    assert item["after"]["planned_end"] == time(11)
    assert len(value.data["targets"]) == 4


def test_noop_replacement_rejected_without_schedule_change_but_allowed_with_real_schedule_patch():
    same = replacement(E1)
    with pytest.raises(ValueError, match="change a business value"):
        production_operation_assignment_targets(operation(), [row()], same)
    values = production_operation_assignment_targets(
        operation(), [row()], same, {"planned_status": "CANCELLED"}
    )
    assert len(values) == 1
    assert (
        values[0]["before"]["equipment_assignments"] == values[0]["after"]["equipment_assignments"]
    )
    assert reload(snapshot(values).data) == snapshot(values)


def test_inactive_reactivation_before_is_fixed_in_child_not_active_parent_collection():
    source = [
        row(),
        row(11, E1, 4, 5, active=False, version=9),
        row(12, E2, 2, 3, active=False, version=5),
    ]
    value = snapshot(targets(source))
    item = parent(value.data)
    assert item["before"]["equipment_assignments"] == [source[0]]
    assert len(value.data["targets"]) == 4
    for target in value.data["targets"]:
        if target["target_type"] != "ProductionOperation":
            assert target["operation_type"] == "UPDATE"
            assert target["after"]["version"] == target["before"]["version"] + 1
    assert reload(value.data) == value


@pytest.mark.parametrize("equipment,end", [(None, 4), (E2, None), (None, None)])
def test_empty_and_unbounded_collection_variants(equipment, end):
    source = [row(end=None)]
    values = production_operation_assignment_targets(
        operation(), source, replacement(equipment, start=0, end=end)
    )
    value = snapshot(values)
    assert reload(value.data) == value
    if equipment is None and end is None:
        assert parent(value.data)["after"]["equipment_assignments"] == []


def test_empty_source_is_explicit_and_create_id_stays_fixed():
    values = targets([])
    value = snapshot(values)
    assert parent(value.data)["before"]["equipment_assignments"] == []
    assert snapshot(values) == reload(value.data) == value
    with pytest.raises(ValueError):
        production_operation_assignment_targets(operation(), None, replacement())


def test_array_order_timezone_audit_and_dict_view_changes_do_not_change_fixed_snapshot(monkeypatch):
    sequence = count(1000)
    monkeypatch.setattr("linescope.assignments.uuid4", lambda: UUID(int=next(sequence)))
    source = [row(), row(11, E1, 12, 14)]
    first = snapshot(targets(source))
    sequence = count(1000)
    other = deepcopy(source[::-1])
    other[1]["effective_from"] = "2026-10-09T09:00:00+09:00"
    other[0]["created_at"] = "outside hash"
    second = snapshot(targets(other))
    assert first == second
    payload = first.data
    payload["targets"].reverse()
    for target in payload["targets"]:
        if target["target_type"] == "ProductionOperation":
            target["before"]["equipment_assignments"].reverse()
            target["after"]["equipment_assignments"].reverse()
    assert snapshot(payload["targets"]) == first
    with pytest.raises(ValueError, match="not canonical"):
        reload(payload)
    payload["targets"].clear()
    assert first.data["targets"]


@pytest.mark.parametrize(
    "change",
    [
        "missing_parent",
        "missing_child",
        "parent_increment",
        "before_collection_version",
        "after_collection_version",
        "before_collection_missing",
        "after_collection_missing",
        "inactive_in_collection",
        "duplicate_collection_id",
        "foreign_parent_in_collection",
        "overlapping_after",
        "child_before_mismatch",
        "child_parent_mismatch",
        "unexpected_after_row",
        "unmatched_collection_changes",
        "one_sided_collection",
        "missing_explicit_null",
    ],
)
def test_cross_target_and_collection_tampering_rejected_even_with_recomputed_hash(change):
    payload = snapshot(targets()).data
    item = parent(payload)
    child = next(
        t
        for t in payload["targets"]
        if t["target_type"] != "ProductionOperation" and t["operation_type"] == "UPDATE"
    )
    if change == "missing_parent":
        payload["targets"].remove(item)
    elif change == "missing_child":
        payload["targets"].remove(child)
    elif change == "parent_increment":
        item["after"]["version"] = 9
    elif change == "before_collection_version":
        item["before"]["equipment_assignments"][0]["version"] = 4
    elif change == "after_collection_version":
        item["after"]["equipment_assignments"][0]["version"] = 5
    elif change == "before_collection_missing":
        item["before"]["equipment_assignments"] = []
    elif change == "after_collection_missing":
        item["after"]["equipment_assignments"] = []
    elif change == "inactive_in_collection":
        item["before"]["equipment_assignments"][0]["active"] = False
    elif change == "duplicate_collection_id":
        item["before"]["equipment_assignments"].append(
            deepcopy(item["before"]["equipment_assignments"][0])
        )
    elif change == "foreign_parent_in_collection":
        item["before"]["equipment_assignments"][0]["production_operation_id"] = str(UUID(int=101))
    elif change == "overlapping_after":
        item["after"]["equipment_assignments"].append(row(99, E1, 1, 5))
    elif change == "child_before_mismatch":
        child["before"]["version"] = 4
        child["expected_version"] = 4
        child["after"]["version"] = 5
    elif change == "child_parent_mismatch":
        for side in ("before", "after", "business_key"):
            child[side]["production_operation_id"] = str(UUID(int=101))
    elif change == "unexpected_after_row":
        item["after"]["equipment_assignments"].append(row(99, E1, 12, 14))
    elif change == "unmatched_collection_changes":
        payload["targets"] = [item]
    elif change == "one_sided_collection":
        del item["after"]["equipment_assignments"]
    elif change == "missing_explicit_null":
        del item["after"]["equipment_assignments"][0]["effective_to"]
    with pytest.raises(ValueError):
        reload(payload)


@pytest.mark.parametrize(
    "patch", [{}, {"planned_status": "PLANNED"}, {"active": False}, {"planned_end": None}]
)
def test_invalid_or_noop_schedule_patch_rejected_even_with_assignment_changes(patch):
    with pytest.raises(ValueError):
        targets(patch=patch)


def test_multiple_operation_targets_and_global_assignment_id_boundaries():
    first = targets()
    second = targets([row(20, op=101)], op=101)
    value = snapshot([*first, *second])
    assert reload(value.data) == value
    # Two parent collections cannot claim the same persisted assignment ID.
    same_id = targets([row(10, op=101)], op=101)
    with pytest.raises(ValueError):
        snapshot([*first, *same_id])


def test_schedule_only_legacy_shape_still_valid_and_assignment_children_cannot_be_attached():
    schedule = production_operation_target(operation(), {"planned_status": "CANCELLED"})
    assert "equipment_assignments" not in schedule["before"]
    assert reload(snapshot([schedule]).data) == snapshot([schedule])
    with pytest.raises(ValueError, match="fixed active collections"):
        snapshot([schedule, *targets()[1:]])


def test_unchanged_assignment_ids_cannot_be_shared_across_parent_collections():
    first = production_operation_assignment_targets(
        operation(), [row()], replacement(E1), {"planned_status": "CANCELLED"}
    )
    second = production_operation_assignment_targets(
        operation(101), [row(op=101)], replacement(E1), {"planned_status": "CANCELLED"}
    )
    with pytest.raises(ValueError, match="Assignment source ID appears under multiple parents"):
        snapshot([*first, *second])


def test_created_id_cannot_collide_with_unchanged_other_parent_assignment():
    first = targets()
    created = next(target for target in first if target["operation_type"] == "CREATE")
    old_id = created["target_id"]
    new_id = str(UUID(int=20))
    created["target_id"] = new_id
    created["after"]["assignment_id"] = new_id
    for item in first[0]["after"]["equipment_assignments"]:
        if item["assignment_id"] == old_id:
            item["assignment_id"] = new_id
    second = production_operation_assignment_targets(
        operation(101), [row(20, op=101)], replacement(E1), {"planned_status": "CANCELLED"}
    )
    with pytest.raises(ValueError, match="conflicts with another parent's source"):
        snapshot([*first, *second])
