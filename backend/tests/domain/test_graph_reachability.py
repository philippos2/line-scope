import pytest

from linescope.domain.graph_reachability import LogicalEdge, bounded_reachability, walk_reachability


def node(identifier, kind="Equipment"):
    return kind, identifier


def edge(source, target, identifier="edge"):
    return LogicalEdge(node(source), node(target), identifier)


def run(edges, **limits):
    return bounded_reachability(
        node("root"), edges, max_depth=limits.get("depth", 5), max_nodes=limits.get("nodes", 20)
    )


def test_shortest_hops_and_root_are_not_changed_by_cycles():
    result = run([edge("root", "a"), edge("a", "b"), edge("b", "root"), edge("root", "b")])
    assert [(r.node, r.distance) for r in result.nodes] == [
        (node("root"), 0),
        (node("a"), 1),
        (node("b"), 1),
    ]
    assert result.nodes[0].predecessor is None
    assert result.nodes[2].predecessor == node("root")
    assert result.complete and result.limit_reason is None


def test_indirect_reachability_and_parent_record():
    result = run([edge("root", "a", "first"), edge("a", "b", "second")])
    assert result.nodes[-1].distance == 2
    assert result.nodes[-1].predecessor == node("a")
    assert result.nodes[-1].source_record_id == "second"


def test_same_layer_and_parallel_edges_choose_deterministic_parent():
    edges = [
        edge("root", "b"),
        edge("root", "a"),
        edge("b", "c", "0"),
        edge("a", "c", "2"),
        edge("a", "c", "1"),
    ]
    forward, reverse = run(edges), run(reversed(edges))
    assert forward == reverse
    assert forward.nodes[-1].predecessor == node("a")
    assert forward.nodes[-1].source_record_id == "1"


@pytest.mark.parametrize("limits", [{"depth": 1}, {"nodes": 2}, {"depth": 1, "nodes": 2}])
def test_exact_boundary_without_unexplored_node_is_complete(limits):
    result = run([edge("root", "a"), edge("a", "root")], **limits)
    assert result.complete and result.limit_reason is None


def test_depth_boundary_requires_an_unexplored_target():
    result = run([edge("root", "a"), edge("a", "b")], depth=1)
    assert [r.node for r in result.nodes] == [node("root"), node("a")]
    assert not result.complete and result.limit_reason == "DEPTH"


def test_node_limit_includes_root_and_selects_sorted_neighbor():
    result = run([edge("root", "b"), edge("root", "a")], nodes=2)
    assert [r.node for r in result.nodes] == [node("root"), node("a")]
    assert not result.complete and result.limit_reason == "NODE_COUNT"


def test_node_limit_has_priority_over_depth():
    result = run([edge("root", "a"), edge("root", "b"), edge("a", "c")], depth=1, nodes=2)
    assert result.limit_reason == "NODE_COUNT"


def test_typed_ids_are_distinct():
    edges = [
        LogicalEdge(node("root"), node("same"), "a"),
        LogicalEdge(node("root"), node("same", "Process"), "b"),
    ]
    assert len(run(edges).nodes) == 3


def test_empty_adjacency_keeps_only_root():
    result = run([], nodes=1)
    assert len(result.nodes) == 1 and result.complete


@pytest.mark.parametrize("value", [0, -1, True, "1", None])
@pytest.mark.parametrize("field", ["depth", "nodes"])
def test_invalid_limits(value, field):
    with pytest.raises(ValueError):
        run([], **{field: value})


def test_timeout_before_expansion_keeps_root_and_does_not_fetch():
    def never_fetch(start):
        raise AssertionError("No expansion budget remains")

    result = walk_reachability(
        node("root"), never_fetch, max_depth=5, max_nodes=20, should_stop=lambda: True
    )
    assert len(result.nodes) == 1 and result.nodes[0].distance == 0
    assert not result.complete and result.limit_reason == "TIMEOUT"


def test_timeout_preserves_confirmed_prefix():
    checks = [0]

    def stop():
        checks[0] += 1
        return checks[0] == 3

    result = walk_reachability(
        node("root"),
        lambda start: [LogicalEdge(start, node("a"), "first")],
        max_depth=5,
        max_nodes=20,
        should_stop=stop,
    )
    assert [item.node for item in result.nodes] == [node("root"), node("a")]
    assert result.nodes[-1].source_record_id == "first"
    assert not result.complete and result.limit_reason == "TIMEOUT"


def test_timeout_overrides_prior_node_count_limit():
    checks = [0]

    def stop():
        checks[0] += 1
        return checks[0] == 4

    result = walk_reachability(
        node("root"),
        lambda start: [LogicalEdge(start, node("a"), "a"), LogicalEdge(start, node("b"), "b")],
        max_depth=5,
        max_nodes=2,
        should_stop=stop,
    )
    assert result.limit_reason == "TIMEOUT" and len(result.nodes) == 2
