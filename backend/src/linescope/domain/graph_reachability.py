"""Deterministic bounded BFS over complete, prefiltered logical adjacency.

Internal pure computation, not a Graph Tool. The caller owns authorization,
generation/as_of filtering, relation directions and complete adjacency reads.
Depth/node limits and an optional server stop checkpoint bound exploration.
Path limits, the total read deadline and Evidence publication remain caller-owned.
"""

from collections import defaultdict
from dataclasses import dataclass

Node = tuple[str, str]


@dataclass(frozen=True)
class LogicalEdge:
    source: Node
    target: Node
    source_record_id: str


@dataclass(frozen=True)
class ReachedNode:
    node: Node
    distance: int
    predecessor: Node | None
    source_record_id: str | None


@dataclass(frozen=True)
class Reachability:
    nodes: tuple[ReachedNode, ...]
    complete: bool
    limit_reason: str | None


def bounded_reachability(root: Node, edges, *, max_depth: int, max_nodes: int):
    """Retain root at distance zero and one deterministic shortest-hop parent.

    Edges are already expressed in logical traversal direction. Optional
    dependencies are retained by the caller; substitutions are excluded.
    A limit is reported only if a distinct reachable node cannot be visited.
    This does not infer failure, feasibility, availability or SPOF.
    """
    _validate_limits(max_depth, max_nodes)
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[edge.source].append(edge)
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda edge: (edge.target, edge.source_record_id))
    return walk_reachability(
        root, lambda node: adjacency[node], max_depth=max_depth, max_nodes=max_nodes
    )


def walk_reachability(root: Node, neighbors, *, max_depth: int, max_nodes: int, should_stop=None):
    """BFS with lazy, complete neighbors ordered by target and record ID.

    The provider may page within a single verified read context. Errors must
    propagate, never become an empty adjacency. Stop fetching a node once an
    unvisited target proves truncation; the result must remain incomplete.
    A cooperative stop preserves confirmed predecessors with TIMEOUT; it does
    not waive the caller's final consistency checks or overall deadline.
    """
    _validate_limits(max_depth, max_nodes)
    reached = {root: ReachedNode(root, 0, None, None)}
    frontier = [root]
    reasons = set()
    stopped = False
    while frontier:
        following = []
        for node in sorted(frontier):
            if should_stop is not None and should_stop():
                reasons.add("TIMEOUT")
                stopped = True
                break
            distance = reached[node].distance
            for edge in neighbors(node):
                if edge.target in reached:
                    continue
                if should_stop is not None and should_stop():
                    reasons.add("TIMEOUT")
                    stopped = True
                    break
                if distance >= max_depth:
                    reasons.add("DEPTH")
                    break
                if len(reached) >= max_nodes:
                    reasons.add("NODE_COUNT")
                    break
                reached[edge.target] = ReachedNode(
                    edge.target, distance + 1, node, edge.source_record_id
                )
                following.append(edge.target)
            if stopped:
                break
        if stopped:
            break
        frontier = following
    reason = (
        "TIMEOUT"
        if "TIMEOUT" in reasons
        else "NODE_COUNT"
        if "NODE_COUNT" in reasons
        else "DEPTH"
        if reasons
        else None
    )
    nodes = tuple(sorted(reached.values(), key=lambda item: (item.distance, item.node)))
    return Reachability(nodes, reason is None, reason)


def _validate_limits(max_depth, max_nodes):
    for value in (max_depth, max_nodes):
        if type(value) is not int or value <= 0:
            raise ValueError("Graph limits must be positive integers")
