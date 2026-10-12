from dataclasses import replace

import pytest

from linescope.domain.graph_common_dependencies import common_dependencies
from linescope.domain.graph_reachability import LogicalEdge, bounded_reachability

A, B, C = ("Product", "A"), ("Product", "B"), ("Product", "C")
PROCESS, INFRA = ("Process", "P"), ("InfrastructureResource", "R")


def search(root, edges, *, max_depth=10):
    return bounded_reachability(root, edges, max_depth=max_depth, max_nodes=20)


def shared_searches():
    edges = [
        LogicalEdge(A, PROCESS, "a"),
        LogicalEdge(B, PROCESS, "b"),
        LogicalEdge(PROCESS, INFRA, "r"),
    ]
    return [(target, search(target, edges)) for target in (A, B)]


def test_shared_candidates_have_verified_ordered_path_for_every_target():
    result = common_dependencies(shared_searches(), max_paths=4)
    assert result.complete and result.limit_reason is None
    assert [item.candidate for item in result.candidates] == [INFRA, PROCESS]
    infrastructure, process = result.candidates
    assert [item.target for item in infrastructure.paths] == [A, B]
    assert [item.path.nodes for item in infrastructure.paths] == [
        (A, PROCESS, INFRA),
        (B, PROCESS, INFRA),
    ]
    assert [item.path.source_record_ids for item in infrastructure.paths] == [
        ("a", "r"),
        ("b", "r"),
    ]
    assert all(item.path.hops == 1 for item in process.paths)
    assert common_dependencies(list(reversed(shared_searches())), max_paths=4) == result


def test_all_three_targets_must_share_candidate():
    searches = shared_searches() + [(C, search(C, [LogicalEdge(C, INFRA, "c")]))]
    result = common_dependencies(searches, max_paths=3)
    assert result.complete and [item.candidate for item in result.candidates] == [INFRA]
    assert len(result.candidates[0].paths) == 3


def test_complete_disjoint_searches_prove_empty_intersection():
    result = common_dependencies([(A, search(A, [])), (B, search(B, []))], max_paths=1)
    assert result.complete and result.candidates == ()


@pytest.mark.parametrize("max_paths,count", [(1, 0), (2, 1), (3, 1), (4, 2)])
def test_path_limit_never_returns_partially_proven_candidate(max_paths, count):
    result = common_dependencies(shared_searches(), max_paths=max_paths)
    assert len(result.candidates) == count
    assert all(len(item.paths) == 2 for item in result.candidates)
    assert result.complete is (max_paths == 4)
    assert result.limit_reason == (None if max_paths == 4 else "PATH_COUNT")


def test_incomplete_search_preserves_positive_candidates_and_reason_priority():
    inputs = [
        (target, replace(reach, complete=False, limit_reason=reason))
        for (target, reach), reason in zip(shared_searches(), ["DEPTH", "TIMEOUT"])
    ]
    result = common_dependencies(inputs, max_paths=2)
    assert len(result.candidates) == 1 and not result.complete
    assert result.limit_reason == "TIMEOUT"


def test_empty_incomplete_search_does_not_prove_no_common_dependencies():
    reach = replace(search(A, []), complete=False, limit_reason="NODE_COUNT")
    result = common_dependencies([(A, reach), (B, search(B, []))], max_paths=1)
    assert result.candidates == () and not result.complete
    assert result.limit_reason == "NODE_COUNT"


def test_input_targets_are_not_candidates_even_when_cycle_reaches_them():
    edges = [LogicalEdge(A, B, "ab"), LogicalEdge(B, A, "ba"), LogicalEdge(A, INFRA, "r")]
    result = common_dependencies(
        [(target, search(target, edges)) for target in (A, B)], max_paths=2
    )
    assert [item.candidate for item in result.candidates] == [INFRA]


@pytest.mark.parametrize("fault", ["single", "duplicate", "root", "predecessor", "complete"])
def test_invalid_or_mismatched_upstream_facts_are_rejected(fault):
    inputs = shared_searches()
    if fault == "single":
        inputs.pop()
    elif fault == "duplicate":
        inputs[1] = inputs[0]
    elif fault == "root":
        inputs[1] = (C, inputs[1][1])
    elif fault == "predecessor":
        reach = inputs[0][1]
        inputs[0] = (
            A,
            replace(
                reach,
                nodes=(reach.nodes[0], replace(reach.nodes[1], predecessor=C), *reach.nodes[2:]),
            ),
        )
    else:
        inputs[0] = (A, replace(inputs[0][1], complete=True, limit_reason="DEPTH"))
    with pytest.raises(ValueError):
        common_dependencies(inputs, max_paths=4)


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5])
def test_invalid_path_limits_are_rejected(limit):
    with pytest.raises(ValueError):
        common_dependencies(shared_searches(), max_paths=limit)


def test_node_identity_includes_entity_type():
    equipment = ("Equipment", "same-id")
    product = ("Product", "same-id")
    process = ("Process", "same-id")
    edges = [LogicalEdge(equipment, process, "ep"), LogicalEdge(product, process, "pp")]
    result = common_dependencies(
        [(root, search(root, edges)) for root in (equipment, product)], max_paths=2
    )
    assert result.complete and result.candidates[0].candidate == process
    assert [item.target for item in result.candidates[0].paths] == [equipment, product]


def test_unshared_shorter_paths_do_not_consume_candidate_proof_budget():
    edges = [
        LogicalEdge(A, ("Equipment", "private-a"), "a-only"),
        LogicalEdge(B, ("Equipment", "private-b"), "b-only"),
        LogicalEdge(A, PROCESS, "ap"),
        LogicalEdge(B, PROCESS, "bp"),
    ]
    result = common_dependencies([(root, search(root, edges)) for root in (A, B)], max_paths=2)
    assert result.complete and [item.candidate for item in result.candidates] == [PROCESS]
