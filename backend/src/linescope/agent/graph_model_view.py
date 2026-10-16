"""Lossless Graph representation for the LLM, separate from server/API results."""

from ..domain.canonical import canonical_json

GRAPH_TOOLS = {
    "trace_downstream_impact",
    "trace_upstream_dependencies",
    "find_common_dependencies",
    "find_alternative_paths",
    "find_single_point_failure_candidates",
}


def graph_model_view(data, evidence):
    nodes, edges = {}, {}
    node_keys, edge_keys = {}, {}

    def compact(value, *, intern_edges=False):
        if isinstance(value, list):
            return [compact(item, intern_edges=intern_edges) for item in value]
        if isinstance(value, dict):
            if set(value) == {"entity_type", "entity_id"}:
                key = canonical_json(value)
                if key not in node_keys:
                    reference = "n" + str(len(nodes) + 1)
                    node_keys[key] = reference
                    nodes[reference] = dict(value)
                return {"node_ref": node_keys[key]}
            result = {}
            for field, item in value.items():
                if intern_edges and field == "edges" and isinstance(item, list):
                    references = []
                    for edge in item:
                        if not isinstance(edge, dict):
                            references.append(compact(edge))
                            continue
                        key = canonical_json(edge)
                        if key not in edge_keys:
                            reference = "e" + str(len(edges) + 1)
                            edge_keys[key] = reference
                            edges[reference] = compact(edge)
                        references.append({"edge_ref": edge_keys[key]})
                    result[field] = references
                else:
                    result[field] = compact(item, intern_edges=intern_edges)
            return result
        return value

    compact_data = compact(data, intern_edges=True)
    compact_evidence = compact(evidence)
    return {
        "data": compact_data,
        "evidence": compact_evidence,
        "graph_node_catalog": nodes,
        "graph_edge_catalog": edges,
    }
