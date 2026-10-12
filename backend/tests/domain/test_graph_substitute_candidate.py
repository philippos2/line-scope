import pytest

from linescope.domain.graph_requirement_rules import equipment_availability, operation_availability
from linescope.domain.graph_substitute_candidate import evaluate_substitute_candidate

CANDIDATE = ("Equipment", "M-208")
ORIGINAL = ("Equipment", "M-204")
UPSTREAM = ("Equipment", "M-300")
OPERATION = ("ProductionOperation", "OP-30")


def evaluate(graph, states, *, candidate=CANDIDATE, excluded=(), complete=True, historical=False):
    return evaluate_substitute_candidate(
        candidate, graph, states, excluded=excluded, complete=complete, historical=historical
    )


def test_running_candidate_and_all_prerequisites_are_required():
    graph = {CANDIDATE: (UPSTREAM, OPERATION), UPSTREAM: (), OPERATION: ()}
    states = {
        CANDIDATE: equipment_availability("RUNNING"),
        UPSTREAM: equipment_availability("RUNNING"),
        OPERATION: operation_availability("PLANNED"),
    }
    assert evaluate(graph, states).availability == "AVAILABLE"
    states[OPERATION] = operation_availability("CANCELLED")
    assert evaluate(graph, states).availability == "UNAVAILABLE"


@pytest.mark.parametrize("state", ["STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"])
def test_relation_existence_does_not_make_candidate_available(state):
    result = evaluate({CANDIDATE: ()}, {CANDIDATE: equipment_availability(state)})
    assert result.availability == equipment_availability(state)
    assert result.structure.determination == "ESTABLISHED"


def test_missing_state_is_unknown_not_unavailable():
    result = evaluate({CANDIDATE: ()}, {})
    assert result.availability == "UNKNOWN"
    assert result.reason == "UNKNOWN_AVAILABILITY"


def test_known_stopped_required_dependency_dominates_an_unknown_state():
    graph = {CANDIDATE: (UPSTREAM,), UPSTREAM: ()}
    result = evaluate(graph, {UPSTREAM: "UNAVAILABLE"})
    assert result.availability == "UNAVAILABLE"


@pytest.mark.parametrize("excluded", [(CANDIDATE,), (UPSTREAM,)])
def test_excluded_candidate_or_required_dependency_cannot_be_replaced(excluded):
    graph = {CANDIDATE: (UPSTREAM,), UPSTREAM: (), ORIGINAL: ()}
    states = {node: "AVAILABLE" for node in graph}
    result = evaluate(graph, states, excluded=excluded)
    assert result.availability == "UNAVAILABLE"
    assert result.structure.determination == "NOT_ESTABLISHED"


def test_candidate_that_depends_on_excluded_original_is_not_a_valid_escape():
    graph = {CANDIDATE: (ORIGINAL,), ORIGINAL: ()}
    result = evaluate(graph, {node: "AVAILABLE" for node in graph}, excluded=(ORIGINAL,))
    assert result.availability == "UNAVAILABLE"


@pytest.mark.parametrize("complete", [True, False])
def test_cycle_or_truncation_cannot_be_assumed_available(complete):
    graph = {CANDIDATE: (UPSTREAM,), UPSTREAM: (CANDIDATE,)}
    result = evaluate(graph, {node: "AVAILABLE" for node in graph}, complete=complete)
    assert result.availability == "UNKNOWN"
    assert result.structure.determination == "INDETERMINATE"


def test_missing_closure_is_unknown_even_when_candidate_runs():
    assert evaluate({CANDIDATE: (UPSTREAM,)}, {CANDIDATE: "AVAILABLE"}).availability == "UNKNOWN"


@pytest.mark.parametrize("entity_type", ["Process", "InfrastructureResource"])
def test_unmodeled_operational_state_remains_unknown(entity_type):
    candidate = (entity_type, "x")
    result = evaluate({candidate: ()}, {candidate: "AVAILABLE"}, candidate=candidate)
    assert result.structure.determination == "ESTABLISHED"
    assert result.availability == "UNKNOWN"


def test_historical_does_not_reuse_current_running_or_stopped_state():
    graph = {CANDIDATE: (UPSTREAM,), UPSTREAM: ()}
    assert (
        evaluate(
            graph, {CANDIDATE: "AVAILABLE", UPSTREAM: "UNAVAILABLE"}, historical=True
        ).availability
        == "UNKNOWN"
    )


def test_disconnected_stopped_state_does_not_affect_candidate():
    graph = {CANDIDATE: (), UPSTREAM: ()}
    assert (
        evaluate(graph, {CANDIDATE: "AVAILABLE", UPSTREAM: "UNAVAILABLE"}).availability
        == "AVAILABLE"
    )


@pytest.mark.parametrize(
    "states,historical",
    [
        ({CANDIDATE: False}, False),
        ({CANDIDATE: None}, False),
        ({CANDIDATE: "RUNNING"}, False),
        ({"x": "AVAILABLE"}, False),
        ([], False),
        ({}, 1),
    ],
)
def test_unvalidated_states_and_analysis_mode_are_rejected(states, historical):
    with pytest.raises(ValueError):
        evaluate({CANDIDATE: ()}, states, historical=historical)


def test_product_is_not_a_substitute_candidate():
    product = ("Product", "p")
    with pytest.raises(ValueError):
        evaluate({product: ()}, {}, candidate=product)
