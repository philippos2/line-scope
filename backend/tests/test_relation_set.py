from copy import deepcopy
from uuid import UUID

import pytest

from linescope.relations import RelationSetConflict, normalize_relation_set

START = "2026-10-09T00:00:00.000000Z"
MID = "2026-10-10T00:00:00.000000Z"
END = "2026-10-11T00:00:00.000000Z"


def row(number, start=START, end=MID, **changes):
    return {
        "dependency_relation_id": str(UUID(int=number)),
        "source_entity_type": "Equipment",
        "source_entity_id": str(UUID(int=100)),
        "target_entity_type": "Equipment",
        "target_entity_id": str(UUID(int=101)),
        "relation_type": "DEPENDS_ON",
        "effective_from": start,
        "effective_to": end,
        "required": True,
        "active": True,
        "version": 1,
        **changes,
    }


def test_adjacent_half_open_periods_and_stable_order():
    first, second = row(1), row(2, MID, None)
    assert normalize_relation_set([second, first]) == [first, second]
    assert normalize_relation_set([]) == []


@pytest.mark.parametrize(
    "first,second",
    [
        (row(1, START, END), row(2, MID, None)),
        (row(1, START, None), row(2, MID, END)),
        (row(1, START, END), row(2, MID, END)),
    ],
)
def test_overlap_and_infinite_end(first, second):
    with pytest.raises(RelationSetConflict, match="Overlapping"):
        normalize_relation_set([second, first])


@pytest.mark.parametrize(
    "changes",
    [
        {"target_entity_id": str(UUID(int=102))},
        {"source_entity_id": str(UUID(int=102))},
        {"source_entity_type": "Process"},
        {"target_entity_type": "Process"},
        {"relation_type": "SUPPLIES"},
    ],
)
def test_distinct_typed_logical_relations_may_overlap(changes):
    normalize_relation_set([row(1, START, END), row(2, MID, END, **changes)])


def test_direction_is_part_of_logical_identity():
    normalize_relation_set(
        [row(1), row(2, source_entity_id=str(UUID(int=101)), target_entity_id=str(UUID(int=100)))]
    )


def test_required_difference_does_not_avoid_overlap():
    with pytest.raises(RelationSetConflict):
        normalize_relation_set([row(1, START, END), row(2, MID, END, required=False)])


def test_inactive_overlap_allowed_but_business_key_still_unique():
    normalize_relation_set([row(1, START, END), row(2, MID, None, active=False)])
    with pytest.raises(RelationSetConflict, match="Duplicate"):
        normalize_relation_set([row(1), row(2, active=False)])


def test_duplicate_id_rejected_even_different_business_key():
    with pytest.raises(RelationSetConflict, match="Duplicate"):
        normalize_relation_set([row(1), row(1, MID, END)])


def test_timezone_normalization_detects_same_business_key():
    with pytest.raises(RelationSetConflict, match="Duplicate"):
        normalize_relation_set([row(1), row(2, "2026-10-09T09:00:00+09:00")])


def test_final_set_after_shortening_or_disabling_allows_new_relation():
    replacement = row(2, MID, END)
    with pytest.raises(RelationSetConflict):
        normalize_relation_set([row(1, START, None), replacement])
    normalize_relation_set([row(1, START, MID), replacement])
    normalize_relation_set([row(1, START, None, active=False), replacement])


def test_normalization_excludes_audit_preserves_inactive_and_does_not_mutate():
    original = row(2, active=False, created_at="audit", updated_at="audit")
    source = deepcopy(original)
    assert normalize_relation_set([original]) == [row(2, active=False)]
    assert original == source


@pytest.mark.parametrize(
    "value", [None, (), [None], [{}], [row(1, START, START)], [row(1, active=1)]]
)
def test_invalid_complete_set_fails_closed(value):
    with pytest.raises(ValueError):
        normalize_relation_set(value)
