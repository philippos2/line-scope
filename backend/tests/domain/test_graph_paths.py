from dataclasses import replace

import pytest

from linescope.domain.graph_paths import representative_paths
from linescope.domain.graph_reachability import (
    LogicalEdge,
    Reachability,
    ReachedNode,
    bounded_reachability,
)

ROOT = ("Equipment", "root")
A = ("Process", "a")
B = ("Product", "b")


def reached(**limits):
    return bounded_reachability(
        ROOT,
        [LogicalEdge(ROOT, A, "first"), LogicalEdge(A, B, "second")],
        max_depth=limits.get("depth", 5),
        max_nodes=limits.get("nodes", 20),
    )


def test_ordered_shortest_paths_retain_typed_nodes_and_record_ids():
    result = representative_paths(reached(), max_paths=2)
    assert result.complete and result.limit_reason is None
    assert result.paths[0].nodes == (ROOT, A)
    assert result.paths[0].source_record_ids == ("first",)
    assert result.paths[0].hops == 1
    assert result.paths[1].nodes == (ROOT, A, B)
    assert result.paths[1].source_record_ids == ("first", "second")
    assert result.paths[1].hops == 2


def test_path_limit_only_marks_an_actually_omitted_path():
    result = representative_paths(reached(), max_paths=1)
    assert len(result.paths) == 1
    assert not result.complete and result.limit_reason == "PATH_COUNT"


def test_root_alone_does_not_consume_a_path():
    result = representative_paths(
        bounded_reachability(ROOT, [], max_depth=1, max_nodes=1), max_paths=1
    )
    assert result.paths == () and result.complete


@pytest.mark.parametrize("reason", ["NODE_COUNT", "DEPTH"])
def test_existing_incompleteness_takes_precedence(reason):
    result = representative_paths(
        replace(reached(), complete=False, limit_reason=reason), max_paths=1
    )
    assert not result.complete and result.limit_reason == reason


@pytest.mark.parametrize("limits,reason", [({"depth": 1}, "DEPTH"), ({"nodes": 2}, "NODE_COUNT")])
def test_truncated_bfs_only_returns_existing_paths(limits, reason):
    result = representative_paths(reached(**limits), max_paths=5)
    assert [path.nodes for path in result.paths] == [(ROOT, A)]
    assert not result.complete and result.limit_reason == reason


def test_reordering_bfs_facts_does_not_change_path_selection():
    original = reached()
    assert representative_paths(original, max_paths=2) == representative_paths(
        replace(original, nodes=tuple(reversed(original.nodes))), max_paths=2
    )


@pytest.mark.parametrize("value", [0, -1, True, "1", None])
def test_invalid_path_limits(value):
    with pytest.raises(ValueError):
        representative_paths(reached(), max_paths=value)


@pytest.mark.parametrize(
    "nodes",
    [
        (),
        (ReachedNode(ROOT, 0, None, None), ReachedNode(ROOT, 0, None, None)),
        (ReachedNode(ROOT, 0, A, "bad"),),
        (ReachedNode(ROOT, 0, None, None), ReachedNode(A, 1, B, "missing")),
        (ReachedNode(ROOT, 0, None, None), ReachedNode(A, 2, ROOT, "wrong-distance")),
        (ReachedNode(ROOT, 0, None, None), ReachedNode(A, 1, A, "cycle")),
        (ReachedNode(ROOT, 0, None, None), ReachedNode(A, 1, ROOT, None)),
        (ReachedNode(ROOT, 0, None, None), ReachedNode(A, True, ROOT, "bool")),
    ],
)
def test_invalid_predecessors_are_not_fabricated_into_paths(nodes):
    with pytest.raises(ValueError):
        representative_paths(Reachability(nodes, True, None), max_paths=1)
