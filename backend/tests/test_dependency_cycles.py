from copy import deepcopy
from uuid import UUID

import pytest

from linescope.dependency_cycles import validate_dependency_cycles


def uid(number):
    return str(UUID(int=number))


def relation(number, source, target, kind="DEPENDS_ON", **changes):
    return {
        "dependency_relation_id": uid(number),
        "source_entity_type": source[0],
        "source_entity_id": uid(source[1]),
        "target_entity_type": target[0],
        "target_entity_id": uid(target[1]),
        "relation_type": kind,
        "required": False,
        "active": True,
        "version": 1,
        "effective_from": "2026-10-09T00:00:00Z",
        "effective_to": None,
        **changes,
    }


def assignment(number=50, operation=3, equipment=1, **changes):
    return {
        "assignment_id": uid(number),
        "production_operation_id": uid(operation),
        "equipment_id": uid(equipment),
        "active": True,
        "version": 1,
        "effective_from": "2026-10-09T00:00:00Z",
        "effective_to": None,
        **changes,
    }


E1, E2, P3 = ("Equipment", 1), ("Equipment", 2), ("Process", 3)


def test_empty_and_disconnected_acyclic_sets():
    validate_dependency_cycles([], [])
    validate_dependency_cycles([relation(10, E1, E2)], [assignment()])


@pytest.mark.parametrize("kind", ["DEPENDS_ON", "CONTROLS", "PRECEDES"])
def test_homogeneous_cycles_and_self_loops(kind):
    first, second = (P3, ("Process", 4)) if kind == "PRECEDES" else (E1, E2)
    for rows in (
        [relation(10, first, first, kind)],
        [relation(10, first, second, kind), relation(11, second, first, kind)],
    ):
        with pytest.raises(ValueError, match="Prohibited"):
            validate_dependency_cycles(rows, [])


def test_storage_cycle_can_be_logically_acyclic():
    validate_dependency_cycles([relation(10, E1, E2), relation(11, E2, E1, "CONTROLS")], [])


def test_storage_parallel_edges_can_form_logical_cycle():
    with pytest.raises(ValueError, match="Prohibited"):
        validate_dependency_cycles([relation(10, E1, E2), relation(11, E1, E2, "CONTROLS")], [])


def test_mixed_controls_depends_on_cycle():
    rows = [relation(10, E1, E2, "CONTROLS"), relation(11, E1, P3), relation(12, P3, E2)]
    with pytest.raises(ValueError, match="Prohibited"):
        validate_dependency_cycles(rows, [])
    rows[-1]["active"] = False
    validate_dependency_cycles(rows, [])


def test_precedes_and_depends_on_mixed_cycle():
    rows = [relation(10, P3, ("Process", 4), "PRECEDES"), relation(11, P3, ("Process", 4))]
    with pytest.raises(ValueError, match="Prohibited"):
        validate_dependency_cycles(rows, [])


def test_uses_and_operation_precedes_are_acyclic_under_endpoint_rules():
    # No allowed dependency endpoint leads back from Equipment to an Operation.
    rows = [
        relation(10, ("ProductionOperation", 3), ("ProductionOperation", 4), "PRECEDES"),
        relation(11, E1, E2),
    ]
    validate_dependency_cycles(rows, [assignment(), assignment(51, operation=4, equipment=2)])


def test_disjoint_periods_and_optional_edges_still_reject_cycle():
    rows = [
        relation(10, E1, E2, effective_to="2026-10-10T00:00:00Z"),
        relation(11, E2, E1, effective_from="2026-10-11T00:00:00Z"),
    ]
    with pytest.raises(ValueError, match="Prohibited"):
        validate_dependency_cycles(rows, [])


@pytest.mark.parametrize("kind", ["SUPPLIES", "CAN_SUBSTITUTE"])
def test_allowed_cycles_are_excluded(kind):
    validate_dependency_cycles([relation(10, E1, E2, kind), relation(11, E2, E1, kind)], [])


def test_typed_ids_parallel_edges_and_input_preservation():
    rows = [
        relation(10, E1, ("Process", 1)),
        relation(11, E1, ("Process", 1)),
        relation(12, ("Process", 1), ("Product", 1), "PRODUCES"),
    ]
    original = deepcopy(rows)
    validate_dependency_cycles(rows, [assignment(), assignment(51)])
    assert rows == original


def test_long_chain_is_iterative():
    rows = [relation(n + 10000, ("Equipment", n), ("Equipment", n + 1)) for n in range(1, 2001)]
    validate_dependency_cycles(rows, [])
    rows.append(relation(20000, ("Equipment", 2001), E1))
    with pytest.raises(ValueError, match="Prohibited"):
        validate_dependency_cycles(rows, [])


@pytest.mark.parametrize("rows,assignments", [(None, []), ([], None), ([{}], []), ([], [{}])])
def test_malformed_input_is_not_treated_as_acyclic(rows, assignments):
    with pytest.raises(ValueError):
        validate_dependency_cycles(rows, assignments)


@pytest.mark.parametrize("kind", ["relation", "assignment"])
def test_duplicate_ids_are_rejected(kind):
    rows, assignments = (
        ([relation(10, E1, E2)] * 2, []) if kind == "relation" else ([], [assignment()] * 2)
    )
    with pytest.raises(ValueError, match="Duplicate"):
        validate_dependency_cycles(rows, assignments)
