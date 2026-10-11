"""Bounded representative paths from server-owned BFS predecessor facts.

Internal computation only. Record IDs must later be resolved to returned,
verified edge facts before constructing public Graph Evidence.
"""

from dataclasses import dataclass

from .graph_reachability import Node, Reachability


@dataclass(frozen=True)
class RepresentativePath:
    nodes: tuple[Node, ...]
    source_record_ids: tuple[str, ...]
    hops: int


@dataclass(frozen=True)
class PathSelection:
    paths: tuple[RepresentativePath, ...]
    complete: bool
    limit_reason: str | None


def representative_paths(reachability: Reachability, *, max_paths: int):
    """Return one shortest-hop path per selected non-root node.

    Preserve NODE_COUNT / DEPTH precedence over PATH_COUNT. Root is not a
    zero-hop path and does not consume the path budget. TIMEOUT and external
    read completeness remain the responsibility of the calling application.
    """
    if type(max_paths) is not int or max_paths <= 0:
        raise ValueError("Path limit must be a positive integer")
    by_node = {item.node: item for item in reachability.nodes}
    roots = [item for item in reachability.nodes if item.distance == 0]
    if len(by_node) != len(reachability.nodes) or len(roots) != 1:
        raise ValueError("BFS must contain unique nodes and exactly one root")
    for item in reachability.nodes:
        if type(item.distance) is not int or item.distance < 0:
            raise ValueError("Invalid BFS distance")
        if item.distance == 0:
            if item.predecessor is not None or item.source_record_id is not None:
                raise ValueError("Root cannot have a predecessor")
        else:
            parent = by_node.get(item.predecessor)
            if (
                parent is None
                or parent.distance != item.distance - 1
                or type(item.source_record_id) is not str
                or not item.source_record_id
            ):
                raise ValueError("Invalid BFS predecessor fact")
    selected = sorted(
        (item for item in reachability.nodes if item.distance > 0),
        key=lambda item: (item.distance, item.node),
    )
    paths = []
    for item in selected[:max_paths]:
        nodes, records, hops = [], [], item.distance
        while item.distance > 0:
            nodes.append(item.node)
            records.append(item.source_record_id)
            item = by_node[item.predecessor]
        nodes.append(item.node)
        paths.append(RepresentativePath(tuple(reversed(nodes)), tuple(reversed(records)), hops))
    omitted = len(selected) > max_paths
    reason = reachability.limit_reason or ("PATH_COUNT" if omitted else None)
    return PathSelection(tuple(paths), reachability.complete and not omitted, reason)
