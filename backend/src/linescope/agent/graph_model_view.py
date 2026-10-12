"""Lossless Graph representation for the LLM, separate from server/API results."""

from ..domain.canonical import canonical_json

GRAPH_TOOLS = {"trace_downstream_impact", "trace_upstream_dependencies"}


def graph_model_view(data, evidence):
    nodes, edges = {}, {}
    node_keys, edge_keys = {}, {}

    def compact(value):
        if isinstance(value, list):
            return [compact(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {"entity_type", "entity_id"}:
                key = canonical_json(value)
                if key not in node_keys:
                    reference = "n" + str(len(nodes) + 1)
                    node_keys[key] = reference
                    nodes[reference] = dict(value)
                return {"node_ref": node_keys[key]}
            return {key: compact(item) for key, item in value.items()}
        return value

    compact_data = compact(data)
    if "representative_paths" in data:
        paths = []
        for path in data["representative_paths"]:
            item = compact(path)
            if not isinstance(path, dict) or not isinstance(path.get("edges"), list):
                paths.append(item)
                continue
            references = []
            for edge in path["edges"]:
                key = canonical_json(edge)
                if key not in edge_keys:
                    reference = "e" + str(len(edges) + 1)
                    edge_keys[key] = reference
                    edges[reference] = compact(edge)
                references.append({"edge_ref": edge_keys[key]})
            item["edges"] = references
            paths.append(item)
        compact_data["representative_paths"] = paths
    compact_evidence = compact(evidence)
    return {
        "data": compact_data,
        "evidence": compact_evidence,
        "graph_node_catalog": nodes,
        "graph_edge_catalog": edges,
    }
