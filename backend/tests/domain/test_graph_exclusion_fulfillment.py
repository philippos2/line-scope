import pytest

from linescope.domain.graph_exclusion_fulfillment import exclusion_fulfillment
from linescope.domain.graph_substitute_selection import select_substitutes_for_exclusion

A = ("Equipment", "M-204")
B = ("Equipment", "M-208")
C = ("Equipment", "M-300")
TARGET = ("Product", "P-100")


def selection(node, candidates, graph, states, **kwargs):
    return select_substitutes_for_exclusion(
        node,
        candidates,
        graph,
        states,
        complete=kwargs.get("complete", True),
        historical=kwargs.get("historical", False),
        excluded=kwargs.get("excluded", ()),
    )


def evaluate(graph, replacements, excluded=(A,), complete=True):
    return exclusion_fulfillment(TARGET, graph, replacements, excluded=excluded, complete=complete)


def test_available_direct_substitute_restores_target():
    graph = {A: (), B: (), TARGET: (A,)}
    replacement = selection(A, [B], graph, {B: "AVAILABLE"})
    assert evaluate(graph, {A: replacement}).determination == "ESTABLISHED"


def test_replacement_does_not_waive_other_mandatory_conditions():
    graph = {A: (), B: (), C: (), TARGET: (A, C)}
    a = selection(A, [B], graph, {B: "AVAILABLE"}, excluded=(C,))
    c = selection(C, [], graph, {}, excluded=(A,))
    assert evaluate(graph, {A: a, C: c}, excluded=(A, C)).determination == "NOT_ESTABLISHED"


def test_candidate_that_requires_excluded_original_does_not_restore_target():
    graph = {A: (), B: (A,), TARGET: (A,)}
    replacement = selection(A, [B], graph, {A: "AVAILABLE", B: "AVAILABLE"})
    assert evaluate(graph, {A: replacement}).determination == "NOT_ESTABLISHED"


@pytest.mark.parametrize("historical", [False, True])
def test_unknown_or_historical_replacement_does_not_prove_no_alternative(historical):
    graph = {A: (), B: (), TARGET: (A,)}
    replacement = selection(A, [B], graph, {}, historical=historical)
    assert evaluate(graph, {A: replacement}).determination == "INDETERMINATE"


def test_missing_replacement_evaluation_is_unknown():
    result = evaluate({A: (), TARGET: (A,)}, {})
    assert result.reason == "UNKNOWN_REPLACEMENT"


def test_complete_empty_candidate_set_proves_unrestored_dependency():
    graph = {A: (), TARGET: (A,)}
    assert evaluate(graph, {A: selection(A, [], graph, {})}).determination == "NOT_ESTABLISHED"


def test_incomplete_replacement_is_global_indeterminate():
    graph = {A: (), B: (), C: (), TARGET: (A, C)}
    a = selection(A, [B], graph, {B: "AVAILABLE"}, complete=False)
    c = selection(C, [], graph, {})
    assert evaluate(graph, {A: a, C: c}, excluded=(A, C)).reason == "INCOMPLETE"


def test_cycle_in_replacement_is_indeterminate():
    graph = {A: (), B: (B,), TARGET: (A,)}
    a = selection(A, [B], graph, {B: "AVAILABLE"})
    assert evaluate(graph, {A: a}).reason == "MANDATORY_CYCLE"


def test_baseline_cycle_is_not_rescued_by_replacement():
    graph = {A: (A,), B: (), TARGET: (A,)}
    a = selection(A, [B], graph, {B: "AVAILABLE"})
    assert evaluate(graph, {A: a}).reason == "MANDATORY_CYCLE"


def test_unrelated_unknown_replacement_does_not_affect_target():
    graph = {A: (), TARGET: ()}
    a = selection(A, [], graph, {}, complete=False)
    assert evaluate(graph, {A: a}).determination == "ESTABLISHED"


def test_missing_closure_is_indeterminate():
    assert evaluate({TARGET: (A,)}, {}).reason == "INCOMPLETE"


def test_truncated_search_is_indeterminate():
    assert evaluate({TARGET: ()}, {}, complete=False).reason == "INCOMPLETE"


def test_two_exclusions_require_two_independent_replacements():
    graph = {A: (), B: (), C: (), TARGET: (A, C)}
    a = selection(A, [B], graph, {B: "AVAILABLE"}, excluded=(C,))
    assert evaluate(graph, {A: a}, excluded=(A, C)).determination == "INDETERMINATE"


@pytest.mark.parametrize("replacement", [None, "AVAILABLE", False])
def test_unvalidated_replacement_values_are_rejected(replacement):
    with pytest.raises(ValueError):
        evaluate({A: (), TARGET: (A,)}, {A: replacement})


def test_replacement_for_nonexcluded_node_is_rejected():
    graph = {A: (), B: (), TARGET: (A,)}
    a = selection(A, [B], graph, {B: "AVAILABLE"})
    with pytest.raises(ValueError):
        evaluate(graph, {B: a})


def test_selection_for_another_original_cannot_be_reused():
    graph = {A: (), B: (), C: (), TARGET: (A,)}
    c = selection(C, [B], graph, {B: "AVAILABLE"})
    with pytest.raises(ValueError):
        evaluate(graph, {A: c})
