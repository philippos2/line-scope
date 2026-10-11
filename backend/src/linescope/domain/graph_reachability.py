"""Deterministic bounded BFS over complete, prefiltered logical adjacency.

Internal pure computation, not a Graph Tool. The caller owns authorization,
generation/as_of filtering, relation directions and complete adjacency reads.
This result covers depth/node limits only; path/time budgets and Evidence
publication must be enforced separately before exposing a Tool result.
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
    for value in (max_depth, max_nodes):
        if type(value) is not int or value <= 0:
            raise ValueError("Graph limits must be positive integers")
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[edge.source].append(edge)
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda edge: (edge.target, edge.source_record_id))
    reached = {root: ReachedNode(root, 0, None, None)}
    frontier = [root]
    reasons = set()
    while frontier:
        following = []
        for node in sorted(frontier):
            distance = reached[node].distance
            for edge in adjacency[node]:
                if edge.target in reached:
                    continue
                if distance >= max_depth:
                    reasons.add("DEPTH")
                    continue
                if len(reached) >= max_nodes:
                    reasons.add("NODE_COUNT")
                    continue
                reached[edge.target] = ReachedNode(
                    edge.target, distance + 1, node, edge.source_record_id
                )
                following.append(edge.target)
        frontier = following
    reason = "NODE_COUNT" if "NODE_COUNT" in reasons else "DEPTH" if reasons else None
    nodes = tuple(sorted(reached.values(), key=lambda item: (item.distance, item.node)))
    return Reachability(nodes, reason is None, reason)
