"""Common server-owned Graph path serialization, without orchestration."""

from ..domain.graph_traversal import traversal_types
from .reads import ToolError

UNEVALUATED_DIMENSIONS = ("OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS")


def _typed(node):
    return {"entity_type": node[0], "entity_id": node[1]}


def serialize_paths(selected_paths, records, direction):
    forward, _ = traversal_types(direction)
    paths = []
    for path in selected_paths:
        edges = []
        for index, record_id in enumerate(path.source_record_ids):
            edge = records[record_id]
            source = (edge["source_type"], edge["source_id"])
            target = (edge["target_type"], edge["target_id"])
            expected = (source, target) if edge["relation_type"] in forward else (target, source)
            if expected != (path.nodes[index], path.nodes[index + 1]):
                raise ToolError("GRAPH_UNAVAILABLE", "Graph path facts are inconsistent")
            edges.append(
                {
                    "source_record_id": record_id,
                    "source_version": edge["source_version"],
                    "relation_type": edge["relation_type"],
                    "required": edge["required"],
                    "source": _typed(source),
                    "target": _typed(target),
                    "traversal_direction": direction,
                    "traversal_source": _typed(path.nodes[index]),
                    "traversal_target": _typed(path.nodes[index + 1]),
                }
            )
        paths.append(
            {
                "nodes": [_typed(node) for node in path.nodes],
                "edges": edges,
                "hops": path.hops,
            }
        )
    return paths
