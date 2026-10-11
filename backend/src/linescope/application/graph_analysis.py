"""Authorized ordinary traversal orchestration and server-built Evidence.

Injected read/state adapters own infrastructure. No Tool registration, HTTP,
LLM execution or mutation. Results are returned only after the read gate exits.
"""

from dataclasses import asdict
from datetime import datetime, timezone

from ..domain.graph_traversal import traversal_types
from .graph_request import GraphLimits, validate_graph_request
from .reads import ReadResult, ToolError, json_value


def _typed(node):
    return {"entity_type": node[0], "entity_id": node[1]}


def _key(node):
    return node[0] + ":" + node[1]


class GraphAnalysis:
    def __init__(self, reader, states, *, system_limits, budget_factory, clock=None, page_size=100):
        if not isinstance(system_limits, GraphLimits):
            raise ValueError("Server Graph limits are required")
        if type(page_size) is not int or page_size <= 0:
            raise ValueError("Internal Graph page size must be positive")
        self.reader, self.states = reader, states
        self.system_limits, self.budget_factory = system_limits, budget_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.page_size = page_size

    def call(self, context, tool, arguments):
        request = validate_graph_request(
            context, tool, arguments, system_limits=self.system_limits, server_time=self.clock()
        )
        limits = request.effective_limits
        budget = self.budget_factory(limits.timeout_ms)
        with self.reader.open(budget) as read:
            result = read.traverse(
                *request.target,
                direction=request.direction,
                as_of=request.as_of,
                max_depth=limits.max_depth,
                max_nodes=limits.max_nodes,
                max_paths=limits.max_paths,
                page_size=self.page_size,
                relation_types=request.relation_types,
            )
            equipment_ids = sorted(
                item.node[1] for item in result.reachability.nodes if item.node[0] == "Equipment"
            )
            observation = self.states.read(equipment_ids, budget)
            records = {edge["source_record_id"]: edge for edge in result.edges}
            forward, _ = traversal_types(request.direction)
            paths = []
            for path in result.paths.paths:
                edges = []
                for index, record_id in enumerate(path.source_record_ids):
                    edge = records[record_id]
                    source = (edge["source_type"], edge["source_id"])
                    target = (edge["target_type"], edge["target_id"])
                    expected = (
                        (source, target) if edge["relation_type"] in forward else (target, source)
                    )
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
                            "traversal_direction": request.direction,
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
            states = sorted(observation["states"] or [], key=lambda state: state["equipment_id"])
            present = {state["equipment_id"] for state in states}
            data = {
                "graph_sync_state": "CURRENT",
                "complete": result.paths.complete,
                "limit_reason": result.paths.limit_reason,
                "requested_limits": dict(request.requested_limits),
                "effective_limits": asdict(limits),
                "target": _typed(request.target),
                "reached_nodes": [
                    _typed(item.node) for item in result.reachability.nodes if item.distance > 0
                ],
                "direct_nodes": [
                    _typed(item.node) for item in result.reachability.nodes if item.distance == 1
                ],
                "indirect_nodes": [
                    _typed(item.node) for item in result.reachability.nodes if item.distance > 1
                ],
                "distances": {_key(item.node): item.distance for item in result.reachability.nodes},
                "representative_paths": paths,
                "determination": None,
            }
            evidence = {
                "source": "NEO4J_AND_POSTGRESQL",
                "tool": tool,
                "graph_generation": read.validation.generation,
                "graph_observed_at": read.observed_at,
                "as_of": request.as_of,
                "temporal_scope": "CURRENT_REGISTRATION_AT_AS_OF",
                "relation_types": list(request.relation_types),
                "state_observed_at": observation["observed_at"],
                "state_versions": {
                    _key(("Equipment", state["equipment_id"])): state["version"] for state in states
                },
                "current_states": states,
                "missing_states": sorted(set(equipment_ids) - present),
                "state_temporal_scope": "CURRENT_STATE_AT_OBSERVATION",
                "representative_paths": paths,
            }
            budget.require()
            response = ReadResult(json_value(data), json_value(evidence))
        return response
