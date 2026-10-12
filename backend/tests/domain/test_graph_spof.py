import pytest

from linescope.domain.graph_spof import evaluate_spof_candidate
from linescope.domain.graph_substitute_selection import select_substitutes_for_exclusion

A = ("Equipment", "M-204")
B = ("Equipment", "M-208")
C = ("Equipment", "M-300")
P = ("Product", "P-100")
Q = ("Product", "P-200")


def selection(graph, candidates=(), states=None, *, complete=True, historical=False):
    return select_substitutes_for_exclusion(
        A, list(candidates), graph, states or {}, complete=complete, historical=historical
    )


def evaluate(
    graph, replacement=None, *, target=P, candidate=A, complete=True, baseline_excluded=()
):
    return evaluate_spof_candidate(
        target,
        candidate,
        graph,
        replacement,
        complete=complete,
        baseline_excluded=baseline_excluded,
    )


def test_mandatory_ancestor_without_available_alternative_is_spof():
    graph = {A: (), P: (A,)}
    result = evaluate(graph, selection(graph))
    assert result.determination == "SPOF"
    assert result.before.determination == "ESTABLISHED"
    assert result.after.determination == "NOT_ESTABLISHED"
    assert result.target == P and result.candidate == A


def test_available_direct_alternative_prevents_spof():
    graph = {A: (), B: (), P: (A,)}
    result = evaluate(graph, selection(graph, (B,), {B: "AVAILABLE"}))
    assert result.determination == "NOT_SPOF"
    assert result.after.determination == "ESTABLISHED"


@pytest.mark.parametrize("state,expected", [("UNKNOWN", "INDETERMINATE"), ("UNAVAILABLE", "SPOF")])
def test_unknown_alternative_is_not_absence(state, expected):
    graph = {A: (), B: (), P: (A,)}
    assert evaluate(graph, selection(graph, (B,), {B: state})).determination == expected


def test_missing_alternative_evaluation_is_indeterminate():
    graph = {A: (), P: (A,)}
    assert evaluate(graph).reason == "UNKNOWN_REPLACEMENT"


def test_candidate_depending_on_original_cannot_prevent_spof():
    graph = {A: (), B: (A,), P: (A,)}
    assert (
        evaluate(graph, selection(graph, (B,), {B: "AVAILABLE", A: "AVAILABLE"})).determination
        == "SPOF"
    )


def test_optional_or_unrelated_node_is_not_a_mandatory_spof():
    graph = {A: (), C: (), P: (C,)}
    result = evaluate(graph)
    assert result.determination == "NOT_SPOF"
    assert result.reason == "NOT_MANDATORY_UPSTREAM"
    assert result.after is None


def test_same_candidate_is_classified_per_target():
    graph = {A: (), B: (), P: (A,), Q: (B,)}
    no_alternative = selection(graph)
    assert evaluate(graph, no_alternative, target=P).determination == "SPOF"
    assert evaluate(graph, no_alternative, target=Q).determination == "NOT_SPOF"


def test_preexisting_failure_cannot_be_attributed_to_candidate():
    graph = {A: (), C: (), P: (A, C)}
    result = evaluate(graph, selection(graph), baseline_excluded=(C,))
    assert result.determination == "INDETERMINATE"
    assert result.reason == "BASELINE_NOT_ESTABLISHED"
    assert result.after is None


def test_already_excluded_candidate_is_not_new_spof():
    graph = {A: (), P: (A,)}
    assert (
        evaluate(graph, selection(graph), baseline_excluded=(A,)).reason
        == "BASELINE_NOT_ESTABLISHED"
    )


@pytest.mark.parametrize("graph", [{A: (A,), P: (A,)}, {P: (A,)}])
def test_baseline_cycle_or_missing_closure_is_indeterminate(graph):
    assert evaluate(graph).determination == "INDETERMINATE"


def test_incomplete_search_is_not_no_candidates():
    graph = {A: (), P: (A,)}
    result = evaluate(graph, selection(graph), complete=False)
    assert result.determination == "INDETERMINATE"
    assert result.reason == "INCOMPLETE"


def test_incomplete_candidate_search_is_indeterminate():
    graph = {A: (), B: (), P: (A,)}
    assert (
        evaluate(graph, selection(graph, (B,), {B: "AVAILABLE"}, complete=False)).reason
        == "INCOMPLETE"
    )


def test_historical_availability_does_not_use_current_running_state():
    graph = {A: (), B: (), P: (A,)}
    assert (
        evaluate(graph, selection(graph, (B,), {B: "AVAILABLE"}, historical=True)).determination
        == "INDETERMINATE"
    )


@pytest.mark.parametrize("candidate", [P, "M-204", ("Equipment", ""), False])
def test_target_itself_and_invalid_candidates_are_rejected(candidate):
    with pytest.raises(ValueError):
        evaluate({A: (), P: (A,)}, candidate=candidate)


def test_other_originals_replacement_evaluation_is_rejected():
    graph = {A: (), B: (), P: (A,)}
    other = select_substitutes_for_exclusion(B, [], graph, {}, complete=True, historical=False)
    with pytest.raises(ValueError):
        evaluate(graph, other)
