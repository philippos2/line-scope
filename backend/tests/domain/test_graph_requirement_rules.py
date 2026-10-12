import pytest

from linescope.domain.graph_requirement_rules import (
    equipment_availability,
    operation_availability,
    required_availability,
    required_dependency,
    substitute_availability,
)


@pytest.mark.parametrize(
    "relation,flag,expected",
    [
        ("DEPENDS_ON", True, True),
        ("DEPENDS_ON", False, False),
        ("SUPPLIES", True, True),
        ("SUPPLIES", False, False),
        ("PRECEDES", False, True),
        ("CONTROLS", False, True),
        ("PRODUCES", False, True),
        ("CAN_SUBSTITUTE", False, False),
        ("USES", None, True),
        ("USES", False, True),
        ("USES", True, True),
    ],
)
def test_required_is_relation_specific_and_uses_is_intrinsic(relation, flag, expected):
    assert required_dependency(relation, flag) is expected


@pytest.mark.parametrize(
    "relation,flag",
    [("SQL", False), ("PRECEDES", True), ("CAN_SUBSTITUTE", True), ("SUPPLIES", None), ("USES", 1)],
)
def test_invalid_relation_flags_fail_closed(relation, flag):
    with pytest.raises(ValueError):
        required_dependency(relation, flag)


@pytest.mark.parametrize(
    "state,expected",
    [
        ("RUNNING", "AVAILABLE"),
        ("STOPPED", "UNAVAILABLE"),
        ("UNDER_MAINTENANCE", "UNAVAILABLE"),
        ("UNKNOWN", "UNKNOWN"),
        (None, "UNKNOWN"),
    ],
)
def test_equipment_availability_comes_from_explicit_state(state, expected):
    assert equipment_availability(state) == expected


@pytest.mark.parametrize(
    "state,expected", [("PLANNED", "AVAILABLE"), ("CANCELLED", "UNAVAILABLE"), (None, "UNKNOWN")]
)
def test_operation_availability_is_planned_status(state, expected):
    assert operation_availability(state) == expected


@pytest.mark.parametrize(
    "function,state",
    [
        (equipment_availability, True),
        (equipment_availability, "DEGRADED"),
        (operation_availability, "RUNNING"),
        (operation_availability, "AVAILABLE"),
    ],
)
def test_registry_active_and_foreign_states_are_not_availability(function, state):
    with pytest.raises(ValueError):
        function(state)


@pytest.mark.parametrize(
    "values,and_result,or_result",
    [
        ([], "AVAILABLE", "UNAVAILABLE"),
        (["AVAILABLE"], "AVAILABLE", "AVAILABLE"),
        (["UNAVAILABLE"], "UNAVAILABLE", "UNAVAILABLE"),
        (["UNKNOWN"], "UNKNOWN", "UNKNOWN"),
        (["AVAILABLE", "UNAVAILABLE"], "UNAVAILABLE", "AVAILABLE"),
        (["AVAILABLE", "UNKNOWN"], "UNKNOWN", "AVAILABLE"),
        (["UNAVAILABLE", "UNKNOWN"], "UNAVAILABLE", "UNKNOWN"),
        (["AVAILABLE", "UNAVAILABLE", "UNKNOWN"], "UNAVAILABLE", "AVAILABLE"),
    ],
)
def test_mandatory_and_and_candidate_or_keep_unknown_distinct(values, and_result, or_result):
    assert required_availability(values, complete=True) == and_result
    assert substitute_availability(values, complete=True) == or_result
    assert required_availability(list(reversed(values)), complete=True) == and_result
    assert substitute_availability(list(reversed(values)), complete=True) == or_result


@pytest.mark.parametrize("values", [[], ["AVAILABLE"], ["UNAVAILABLE"], ["UNKNOWN"]])
@pytest.mark.parametrize("function", [required_availability, substitute_availability])
def test_incomplete_search_cannot_become_definitive_availability(function, values):
    assert function(values, complete=False) == "UNKNOWN"


@pytest.mark.parametrize(
    "values,complete",
    [
        ([False], True),
        ([0], True),
        ([None], True),
        (["NONE"], True),
        (["UNKNOWN"], 1),
        (["UNKNOWN"], "true"),
    ],
)
@pytest.mark.parametrize("function", [required_availability, substitute_availability])
def test_unknown_zero_false_and_untrusted_completeness_are_not_interchangeable(
    function, values, complete
):
    with pytest.raises(ValueError):
        function(values, complete=complete)
