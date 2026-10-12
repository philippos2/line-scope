import pytest

from linescope.domain.graph_substitute_selection import select_substitutes_for_exclusion

ORIGINAL = ("Equipment", "M-204")
A = ("Equipment", "M-208")
B = ("Equipment", "M-300")
C = ("Equipment", "M-400")


def select(candidates, graph, states, *, complete=True, historical=False, excluded=()):
    return select_substitutes_for_exclusion(
        ORIGINAL,
        candidates,
        graph,
        states,
        complete=complete,
        historical=historical,
        excluded=excluded,
    )


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("AVAILABLE", "UNKNOWN", "AVAILABLE"),
        ("AVAILABLE", "UNAVAILABLE", "AVAILABLE"),
        ("UNKNOWN", "UNAVAILABLE", "UNKNOWN"),
        ("UNKNOWN", "UNKNOWN", "UNKNOWN"),
        ("UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE"),
    ],
)
def test_or_keeps_unknown_distinct_and_is_order_independent(a, b, expected):
    graph = {A: (), B: ()}
    states = {A: a, B: b}
    forward = select([A, B], graph, states)
    assert forward.availability == expected
    assert forward == select([B, A, A], graph, states)
    assert [item.node for item in forward.candidates] == [A, B]


@pytest.mark.parametrize("complete,expected", [(True, "UNAVAILABLE"), (False, "UNKNOWN")])
def test_empty_set_is_no_substitute_only_if_complete(complete, expected):
    result = select([], {}, {}, complete=complete)
    assert result.availability == expected
    assert result.complete is complete


def test_original_is_excluded_even_if_its_current_state_is_running():
    result = select([A], {A: (ORIGINAL,), ORIGINAL: ()}, {A: "AVAILABLE", ORIGINAL: "AVAILABLE"})
    assert result.availability == "UNAVAILABLE"


def test_other_exclusions_are_not_waived():
    result = select([A], {A: (C,), C: ()}, {A: "AVAILABLE", C: "AVAILABLE"}, excluded=(C,))
    assert result.availability == "UNAVAILABLE"


def test_disconnected_available_object_cannot_rescue_candidate_dependency():
    result = select(
        [A], {A: (C,), C: (), B: ()}, {A: "AVAILABLE", B: "AVAILABLE", C: "UNAVAILABLE"}
    )
    assert result.availability == "UNAVAILABLE"
    assert [item.node for item in result.candidates] == [A]


def test_unknown_candidate_does_not_mean_no_candidate():
    result = select([A], {A: ()}, {})
    assert len(result.candidates) == 1
    assert result.availability == "UNKNOWN"
    assert result.reason == "UNKNOWN_AVAILABILITY"


def test_incomplete_candidate_closure_overrides_another_available_candidate():
    result = select([A, B], {A: (), B: (C,)}, {A: "AVAILABLE", B: "AVAILABLE"})
    assert result.availability == "UNKNOWN"
    assert result.complete is False
    assert result.reason == "INCOMPLETE"


def test_mandatory_cycle_is_not_assumed_to_hold():
    result = select(
        [A, B], {A: (), B: (C,), C: (B,)}, {A: "AVAILABLE", B: "AVAILABLE", C: "AVAILABLE"}
    )
    assert result.availability == "UNKNOWN"
    assert result.complete is True
    assert result.reason == "MANDATORY_CYCLE"


def test_truncation_overrides_known_available_candidate():
    assert select([A], {A: ()}, {A: "AVAILABLE"}, complete=False).availability == "UNKNOWN"


def test_historical_states_are_not_current_states():
    assert select([A], {A: ()}, {A: "AVAILABLE"}, historical=True).availability == "UNKNOWN"


@pytest.mark.parametrize(
    "candidates", [[ORIGINAL], [("Process", "M-208")], ["M-208"], [("Equipment", "")], "M-208"]
)
def test_invalid_candidates_are_rejected(candidates):
    with pytest.raises(ValueError):
        select(candidates, {}, {})


@pytest.mark.parametrize(
    "states,excluded,complete,historical",
    [(False, (), True, False), ({}, (False,), True, False), ({}, (), 1, False), ({}, (), True, 1)],
)
def test_empty_candidates_do_not_bypass_input_validation(states, excluded, complete, historical):
    with pytest.raises(ValueError):
        select([], {}, states, excluded=excluded, complete=complete, historical=historical)
