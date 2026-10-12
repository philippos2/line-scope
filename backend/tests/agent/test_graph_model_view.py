from copy import deepcopy

from linescope.agent.graph_model_view import graph_model_view
from linescope.domain.canonical import canonical_json


def restore(value, view):
    if isinstance(value, list):
        return [restore(item, view) for item in value]
    if isinstance(value, dict):
        for field, catalog in (
            ("node_ref", "graph_node_catalog"),
            ("edge_ref", "graph_edge_catalog"),
        ):
            if set(value) == {field}:
                return restore(view[catalog][value[field]], view)
        return {key: restore(item, view) for key, item in value.items()}
    return value


def test_all_paths_attributes_and_metadata_survive_compaction():
    nodes = [
        {"entity_type": "Equipment", "entity_id": "20400000-0000-4000-8000-000000000001"},
        {"entity_type": "Process", "entity_id": "20400000-0000-4000-8000-000000000002"},
    ]
    edge = {
        "source": nodes[0],
        "target": nodes[1],
        "traversal_source": nodes[0],
        "traversal_target": nodes[1],
        "relation_type": "SUPPLIES",
        "required": True,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": None,
    }
    paths = [{"nodes": nodes, "edges": [edge]} for _ in range(6)]
    data = {
        "target": nodes[0],
        "reached_nodes": nodes[1:],
        "representative_paths": paths,
        "complete": False,
        "limit_reason": "DEPTH",
        "analysis_mode": "CURRENT",
    }
    evidence = {
        "graph_generation": "g1",
        "state_versions": {"Equipment:" + nodes[0]["entity_id"]: 14},
    }
    before = deepcopy((data, evidence))
    view = graph_model_view(data, evidence)
    assert restore(view["data"], view) == data
    assert restore(view["evidence"], view) == evidence
    assert len(view["graph_node_catalog"]) == 2
    assert len(view["graph_edge_catalog"]) == 1
    assert len(view["data"]["representative_paths"]) == 6
    assert len(canonical_json(view)) < len(canonical_json({"data": data, "evidence": evidence}))
    assert (data, evidence) == before


def test_distinct_edge_semantics_are_never_merged():
    data = {
        "representative_paths": [
            {"nodes": [], "edges": [{"required": True}]},
            {"nodes": [], "edges": [{"required": False}]},
        ]
    }
    evidence = {"representative_paths": [{"nodes": [], "edges": [{"required": None}]}]}
    view = graph_model_view(data, evidence)
    assert len(view["graph_edge_catalog"]) == 2
    assert restore(view["data"], view) == data
    assert restore(view["evidence"], view) == evidence
