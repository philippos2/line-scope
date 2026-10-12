import pytest

from linescope.domain.graph_fulfillment import structural_fulfillment

A = ("Equipment", "a")
B = ("Process", "b")
C = ("Product", "c")
D = ("Equipment", "d")


def evaluate(graph, *, target=C, excluded=(), complete=True):
    return structural_fulfillment(target, graph, excluded=excluded, complete=complete)


def test_all_mandatory_branches_must_hold_despite_another_path():
    graph = {A: (), B: (A,), C: (A, B)}
    assert evaluate(graph).determination == "ESTABLISHED"
    assert evaluate(graph, excluded=(B,)).determination == "NOT_ESTABLISHED"
    assert evaluate(graph, excluded=(A,)).determination == "NOT_ESTABLISHED"


def test_source_is_structurally_established_without_operational_guarantee():
    assert evaluate({C: ()}).determination == "ESTABLISHED"
    assert evaluate({C: ()}, excluded=(C,)).determination == "NOT_ESTABLISHED"


def test_disconnected_exclusion_and_cycle_do_not_affect_target():
    graph = {C: (), A: (B,), B: (A,)}
    assert evaluate(graph, excluded=(A,)).determination == "ESTABLISHED"


@pytest.mark.parametrize("excluded", [(), (A,), (C,)])
def test_mandatory_cycle_is_indeterminate_even_if_excluded(excluded):
    result = evaluate({A: (B,), B: (A,), C: (A,)}, excluded=excluded)
    assert result.determination == "INDETERMINATE"
    assert result.reason == "MANDATORY_CYCLE"


def test_self_cycle_is_indeterminate():
    assert evaluate({C: (C,)}).reason == "MANDATORY_CYCLE"


@pytest.mark.parametrize("graph", [{}, {C: (A,)}, {C: (B,), B: (A,)}])
def test_missing_prerequisite_is_not_a_source(graph):
    assert evaluate(graph).reason == "INCOMPLETE"


@pytest.mark.parametrize("excluded", [(), (C,)])
def test_incomplete_search_never_gives_definitive_result(excluded):
    result = evaluate({C: ()}, excluded=excluded, complete=False)
    assert result.determination == "INDETERMINATE"
    assert result.reason == "INCOMPLETE"


def test_duplicate_prerequisites_and_shared_diamond_do_not_create_cycle():
    graph = {A: (), B: (A, A), D: (A,), C: (B, D)}
    assert evaluate(graph).determination == "ESTABLISHED"
    assert evaluate(graph, excluded=(A,)).determination == "NOT_ESTABLISHED"


def test_typed_identity_is_preserved():
    other = ("Process", "a")
    assert evaluate({A: (), other: (), C: (A,)}, excluded=(other,)).determination == "ESTABLISHED"


def test_long_chain_does_not_use_recursive_call_stack():
    nodes = [("Process", str(index)) for index in range(2000)]
    graph = {node: (nodes[index - 1],) if index else () for index, node in enumerate(nodes)}
    assert evaluate(graph, target=nodes[-1]).determination == "ESTABLISHED"
    assert (
        evaluate(graph, target=nodes[-1], excluded=(nodes[0],)).determination == "NOT_ESTABLISHED"
    )


@pytest.mark.parametrize(
    "target,graph,excluded,complete",
    [
        ("c", {C: ()}, (), True),
        (C, [], (), True),
        (C, {C: "a"}, (), True),
        (C, {C: ("a",)}, (), True),
        (C, {C: ()}, "a", True),
        (C, {C: ()}, (False,), True),
        (C, {C: ()}, (), 1),
        (C, {C: ()}, (), None),
    ],
)
def test_malformed_inputs_are_rejected(target, graph, excluded, complete):
    with pytest.raises(ValueError):
        evaluate(graph, target=target, excluded=excluded, complete=complete)
