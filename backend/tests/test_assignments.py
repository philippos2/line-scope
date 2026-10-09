from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import UUID

import pytest

from linescope.assignments import replacement_assignment_targets, validate_assignment_target
from linescope.canonical import normalize_timestamp

OPERATION = str(UUID(int=100))
E1, E2 = str(UUID(int=1)), str(UUID(int=2))
BASE = datetime(2026, 10, 9, tzinfo=timezone.utc)


def at(hour):
    return normalize_timestamp(BASE + timedelta(hours=hour))


def row(start=0, end=6, equipment=E1, identifier=10, active=True, version=3):
    return {
        "assignment_id": str(UUID(int=identifier)),
        "production_operation_id": OPERATION,
        "equipment_id": equipment,
        "effective_from": at(start),
        "effective_to": at(end) if end is not None else None,
        "active": active,
        "version": version,
    }


def replace(rows, start=2, end=4, equipment_ids=None):
    return replacement_assignment_targets(
        OPERATION,
        rows,
        {
            "effective_from": at(start),
            "effective_to": at(end) if end is not None else None,
            "equipment_ids": [E2] if equipment_ids is None else equipment_ids,
        },
    )


def applied(rows, targets):
    result = {item["assignment_id"]: deepcopy(item) for item in rows}
    for target in targets:
        result[target["target_id"]] = target["after"]
    return list(result.values())


def active_intervals(rows):
    return sorted(
        (item["equipment_id"], item["effective_from"], item["effective_to"])
        for item in rows
        if item["active"]
    )


def equipment_at(rows, time):
    return {
        item["equipment_id"]
        for item in rows
        if item["active"]
        and item["effective_from"] <= time
        and (item["effective_to"] is None or time < item["effective_to"])
    }


def test_middle_replacement_preserves_both_outside_intervals_and_reuses_left_id():
    source = [row()]
    original = deepcopy(source)
    targets = replace(source)
    assert source == original
    assert active_intervals(applied(source, targets)) == [
        (E1, at(0), at(2)),
        (E1, at(4), at(6)),
        (E2, at(2), at(4)),
    ]
    update = next(target for target in targets if target["operation_type"] == "UPDATE")
    assert update["target_id"] == source[0]["assignment_id"]
    assert update["expected_version"] == 3 and update["after"]["version"] == 4
    for target in targets:
        assert validate_assignment_target(target) == target
        if target["operation_type"] == "CREATE":
            assert target["before"] is None and target["expected_version"] is None
            assert target["after"]["version"] == 1


@pytest.mark.parametrize(
    "old_start,old_end,start,end,expected",
    [
        (0, 6, 0, 6, []),
        (0, 6, 0, 2, [(E1, at(2), at(6))]),
        (0, 6, 4, 6, [(E1, at(0), at(4))]),
        (0, 6, 2, 4, [(E1, at(0), at(2)), (E1, at(4), at(6))]),
        (0, None, 2, 4, [(E1, at(0), at(2)), (E1, at(4), None)]),
        (0, None, 2, None, [(E1, at(0), at(2))]),
        (4, 6, 2, None, []),
        (0, 2, 2, 4, [(E1, at(0), at(2))]),
        (4, 6, 2, 4, [(E1, at(4), at(6))]),
    ],
)
def test_empty_set_cutting_and_half_open_boundaries(old_start, old_end, start, end, expected):
    source = [row(old_start, old_end)]
    assert active_intervals(applied(source, replace(source, start, end, []))) == expected


def test_desired_existing_coverage_is_not_split_and_only_gaps_are_created():
    source = [row(0, 2), row(4, 6, identifier=11)]
    targets = replace(source, 1, 5, [E1])
    assert len(targets) == 1 and targets[0]["operation_type"] == "CREATE"
    assert active_intervals(applied(source, targets)) == [
        (E1, at(0), at(2)),
        (E1, at(2), at(4)),
        (E1, at(4), at(6)),
    ]
    assert replace([row(0, None)], 2, 4, [E1]) == []
    assert replace([row(0, None)], 2, None, [E1]) == []
    assert replace([row(0, 2), row(2, 6, identifier=11)], 1, 5, [E1]) == []


def test_inactive_business_keys_are_reactivated_with_version_and_before_values():
    source = [
        row(),
        row(4, 5, identifier=11, active=False, version=9),
        row(2, 3, equipment=E2, identifier=12, active=False, version=7),
    ]
    targets = replace(source)
    assert {item["operation_type"] for item in targets} == {"UPDATE"}
    assert {item["target_id"] for item in targets} == {item["assignment_id"] for item in source}
    assert active_intervals(applied(source, targets)) == [
        (E1, at(0), at(2)),
        (E1, at(4), at(6)),
        (E2, at(2), at(4)),
    ]
    for target in targets:
        assert target["before"] == next(
            item for item in source if item["assignment_id"] == target["target_id"]
        )
        assert target["after"]["version"] == target["expected_version"] + 1


def test_unbounded_replacement_removes_future_rows_and_disables_without_rewriting_periods():
    source = [row(0, 3), row(4, None, identifier=11)]
    targets = replace(source, 2, None, [E2])
    assert active_intervals(applied(source, targets)) == [(E1, at(0), at(2)), (E2, at(2), None)]
    disabled = next(item for item in targets if item["operation_type"] == "DISABLE")
    assert disabled["before"]["effective_from"] == disabled["after"]["effective_from"]
    assert disabled["before"]["effective_to"] == disabled["after"]["effective_to"]
    assert disabled["after"]["active"] is False


def test_input_order_timezone_and_audit_values_do_not_affect_generated_targets(monkeypatch):
    source = [row(), row(0, 1, equipment=E2, identifier=11)]
    ids = count(1000)
    monkeypatch.setattr("linescope.assignments.uuid4", lambda: UUID(int=next(ids)))
    first = replace(source, equipment_ids=[E2, E1])
    ids = count(1000)
    changed = deepcopy(source[::-1])
    changed[0]["effective_from"] = "2026-10-09T09:00:00+09:00"
    changed[0]["created_at"] = "audit outside hash"
    assert first == replace(changed, equipment_ids=[E1, E2])


@pytest.mark.parametrize(
    "replacement",
    [
        {"effective_from": at(2), "equipment_ids": []},
        {"effective_to": None, "equipment_ids": []},
        {"effective_from": at(2), "effective_to": at(2), "equipment_ids": []},
        {"effective_from": at(4), "effective_to": at(2), "equipment_ids": []},
        {"effective_from": "2026-10-09T00:00:00", "effective_to": None, "equipment_ids": []},
        {"effective_from": at(2), "effective_to": None, "equipment_ids": [E1, E1]},
        {"effective_from": at(2), "effective_to": None, "equipment_ids": ["invalid"]},
        {"effective_from": at(2), "effective_to": None, "equipment_ids": None},
        {"effective_from": at(2), "effective_to": None, "equipment_ids": [], "version": 1},
    ],
)
def test_replacement_requires_explicit_end_valid_interval_and_distinct_uuid_set(replacement):
    with pytest.raises(ValueError):
        replacement_assignment_targets(OPERATION, [], replacement)


@pytest.mark.parametrize(
    "change",
    ["parent", "id", "key", "overlap", "infinite_overlap", "bool", "version", "missing", "extra"],
)
def test_invalid_or_inconsistent_source_rejected(change):
    source = [row()]
    if change == "parent":
        source[0]["production_operation_id"] = E1
    elif change == "id":
        source.append(row(7, 8))
    elif change == "key":
        source.append(row(0, 4, identifier=11, active=False))
    elif change == "overlap":
        source.append(row(5, 8, identifier=11))
    elif change == "infinite_overlap":
        source = [row(0, None), row(6, 8, identifier=11)]
    elif change == "bool":
        source[0]["active"] = 1
    elif change == "version":
        source[0]["version"] = True
    elif change == "missing":
        del source[0]["effective_to"]
    elif change == "extra":
        source[0]["unknown"] = "value"
    with pytest.raises(ValueError):
        replace(source)


def test_version_overflow_only_blocks_changed_rows_and_id_collision_is_rejected(monkeypatch):
    assert replace([row(version=2**63 - 1)], equipment_ids=[E1]) == []
    with pytest.raises(ValueError):
        replace([row(version=2**63 - 1)])
    monkeypatch.setattr("linescope.assignments.uuid4", lambda: UUID(int=10))
    with pytest.raises(ValueError, match="collision"):
        replace([row()])


@pytest.mark.parametrize(
    "change",
    ["expected", "version", "parent", "equipment", "start", "key", "operation", "noop", "audit"],
)
def test_assignment_target_tampering_rejected(change):
    target = next(item for item in replace([row()]) if item["operation_type"] == "UPDATE")
    if change == "expected":
        target["expected_version"] = 2
    elif change == "version":
        target["after"]["version"] = 9
    elif change == "parent":
        target["after"]["production_operation_id"] = E1
    elif change == "equipment":
        target["after"]["equipment_id"] = E2
    elif change == "start":
        target["after"]["effective_from"] = at(1)
    elif change == "key":
        target["business_key"]["equipment_id"] = E2
    elif change == "operation":
        target["operation_type"] = "DISABLE"
    elif change == "noop":
        target["after"]["effective_to"] = target["before"]["effective_to"]
    elif change == "audit":
        target["after"]["updated_at"] = at(1)
    with pytest.raises(ValueError):
        validate_assignment_target(target)


def test_interval_replacement_matches_pointwise_set_semantics_across_1008_cases():
    cases = 0
    for old_start in range(4):
        for old_end in [*range(old_start + 1, 5), None]:
            source = [row(old_start, old_end)]
            for start in range(4):
                for end in [*range(start + 1, 6), None]:
                    for desired in [[], [E1], [E2], [E1, E2]]:
                        result = applied(source, replace(source, start, end, desired))
                        for hour in range(-1, 8):
                            for offset in [0, 0.5]:
                                point = at(hour + offset)
                                inside = at(start) <= point and (end is None or point < at(end))
                                expected = set(desired) if inside else equipment_at(source, point)
                                assert equipment_at(result, point) == expected
                        intervals = [item for item in result if item["active"]]
                        for index, left in enumerate(intervals):
                            for right in intervals[index + 1 :]:
                                if left["equipment_id"] == right["equipment_id"]:
                                    assert (
                                        left["effective_to"] is not None
                                        and left["effective_to"] <= right["effective_from"]
                                    ) or (
                                        right["effective_to"] is not None
                                        and right["effective_to"] <= left["effective_from"]
                                    )
                        cases += 1
    assert cases == 1008
