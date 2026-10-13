"""Authorized ordinary traversal orchestration and server-built Evidence.

Injected read/state adapters own infrastructure. No Tool registration, HTTP,
LLM execution or mutation. Results are returned only after the read gate exits.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from math import isfinite

from ..domain.graph_common_dependencies import common_dependencies
from .alternative_analysis import evaluate_alternative_facts
from .alternative_evidence import build_alternative_result
from .graph_evidence import UNEVALUATED_DIMENSIONS, serialize_paths
from .graph_request import (
    GraphLimits,
    validate_alternative_request,
    validate_common_dependency_request,
    validate_graph_request,
    validate_spof_request,
)
from .reads import ReadResult, json_value
from .spof_analysis import evaluate_spof_facts
from .spof_evidence import build_spof_result


def _typed(node):
    return {"entity_type": node[0], "entity_id": node[1]}


def _key(node):
    return node[0] + ":" + node[1]


class GraphAnalysis:
    def __init__(
        self,
        reader,
        states,
        *,
        system_limits,
        budget_factory,
        clock=None,
        page_size=100,
        completion_reserve_ms=None,
    ):
        if not isinstance(system_limits, GraphLimits):
            raise ValueError("Server Graph limits are required")
        if type(page_size) is not int or page_size <= 0:
            raise ValueError("Internal Graph page size must be positive")
        self.reader, self.states = reader, states
        self.system_limits, self.budget_factory = system_limits, budget_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.page_size = page_size
        reserve = (
            system_limits.timeout_ms / 10
            if completion_reserve_ms is None
            else completion_reserve_ms
        )
        if (
            type(reserve) not in (int, float)
            or not isfinite(reserve)
            or reserve <= 0
            or reserve >= system_limits.timeout_ms
        ):
            raise ValueError("Completion reserve must be positive and below the total timeout")
        self.completion_reserve_ms = reserve

    def call(self, context, tool, arguments):
        if tool == "find_single_point_failure_candidates":
            return self._spof(context, arguments)
        if tool == "find_alternative_paths":
            return self._alternative(context, arguments)
        if tool == "find_common_dependencies":
            return self._common(context, arguments)
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
                should_stop=lambda: budget.remaining() <= self.completion_reserve_ms / 1000,
            )
            equipment_ids = sorted(
                item.node[1] for item in result.reachability.nodes if item.node[0] == "Equipment"
            )
            observation = self.states.read(equipment_ids, budget)
            records = {edge["source_record_id"]: edge for edge in result.edges}
            paths = serialize_paths(result.paths.paths, records, request.direction)
            states = sorted(observation["states"] or [], key=lambda state: state["equipment_id"])
            present = {state["equipment_id"] for state in states}
            analysis_mode = "EXPLICIT_HISTORICAL" if "explicit_as_of" in arguments else "CURRENT"
            data = {
                "analysis_mode": analysis_mode,
                "analysis_scope": "DEPENDENCY_REACHABILITY",
                "not_evaluated": list(UNEVALUATED_DIMENSIONS),
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
                "analysis_mode": analysis_mode,
                "analysis_scope": "DEPENDENCY_REACHABILITY",
                "not_evaluated": list(UNEVALUATED_DIMENSIONS),
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

    def _common(self, context, arguments):
        request = validate_common_dependency_request(
            context,
            arguments,
            system_limits=self.system_limits,
            server_time=self.clock(),
        )
        limits = request.effective_limits
        budget = self.budget_factory(limits.timeout_ms)
        with self.reader.open(budget) as read:
            searches = read.common_dependency_searches(
                request.targets,
                as_of=request.as_of,
                max_depth=limits.max_depth,
                max_nodes=limits.max_nodes,
                page_size=self.page_size,
                relation_types=request.relation_types,
                should_stop=lambda: budget.remaining() <= self.completion_reserve_ms / 1000,
            )
            selected = common_dependencies(
                [(target, result.reachability) for target, result in searches],
                max_paths=limits.max_paths,
            )
            equipment_ids = sorted(
                {
                    node.node[1]
                    for _, result in searches
                    for node in result.reachability.nodes
                    if node.node[0] == "Equipment"
                }
            )
            observation = self.states.read(equipment_ids, budget)
            records = {
                edge["source_record_id"]: edge for _, result in searches for edge in result.edges
            }
            paths = []
            for candidate in selected.candidates:
                for item in candidate.paths:
                    path = serialize_paths([item.path], records, "UPSTREAM")[0]
                    paths.append(
                        {
                            "target": _typed(item.target),
                            "candidate": _typed(candidate.candidate),
                            **path,
                        }
                    )
            states = sorted(observation["states"] or [], key=lambda state: state["equipment_id"])
            mode = "EXPLICIT_HISTORICAL" if "explicit_as_of" in arguments else "CURRENT"
            scope = {
                "analysis_mode": mode,
                "analysis_scope": "DEPENDENCY_REACHABILITY",
                "not_evaluated": list(UNEVALUATED_DIMENSIONS),
            }
            data = {
                **scope,
                "targets": [_typed(target) for target in request.targets],
                "common_candidates": [_typed(item.candidate) for item in selected.candidates],
                "representative_paths": paths,
                "graph_sync_state": "CURRENT",
                "complete": selected.complete,
                "limit_reason": selected.limit_reason,
                "requested_limits": dict(request.requested_limits),
                "effective_limits": asdict(limits),
                "determination": None,
            }
            evidence = {
                **scope,
                "source": "NEO4J_AND_POSTGRESQL",
                "tool": "find_common_dependencies",
                "graph_generation": read.validation.generation,
                "graph_observed_at": read.observed_at,
                "as_of": request.as_of,
                "temporal_scope": "CURRENT_REGISTRATION_AT_AS_OF",
                "relation_types": list(request.relation_types),
                "representative_paths": paths,
                "state_observed_at": observation["observed_at"],
                "state_versions": {
                    _key(("Equipment", state["equipment_id"])): state["version"] for state in states
                },
                "current_states": states,
                "missing_states": sorted(
                    set(equipment_ids) - {state["equipment_id"] for state in states}
                ),
                "state_temporal_scope": "CURRENT_STATE_AT_OBSERVATION",
            }
            budget.require()
            response = ReadResult(json_value(data), json_value(evidence))
        return response

    def _alternative(self, context, arguments):
        request = validate_alternative_request(
            context, arguments, system_limits=self.system_limits, server_time=self.clock()
        )
        limits = request.effective_limits
        budget = self.budget_factory(limits.timeout_ms)
        historical = "explicit_as_of" in arguments
        with self.reader.open(budget) as read:
            facts = read.alternative_facts(
                request.important_targets,
                request.excluded_nodes,
                as_of=request.as_of,
                max_depth=limits.max_depth,
                max_nodes=limits.max_nodes,
                page_size=self.page_size,
                should_stop=lambda: budget.remaining() <= self.completion_reserve_ms / 1000,
            )
            evaluation = evaluate_alternative_facts(
                facts, self.states, budget, historical=historical
            )
            response = build_alternative_result(
                facts,
                evaluation,
                budget,
                max_paths=limits.max_paths,
                graph_generation=read.validation.generation,
                graph_observed_at=read.observed_at,
                as_of=request.as_of,
                historical=historical,
            )
            response.data["requested_limits"] = dict(request.requested_limits)
            response.data["effective_limits"] = asdict(limits)
            budget.require()
        return response

    def _spof(self, context, arguments):
        request = validate_spof_request(
            context, arguments, system_limits=self.system_limits, server_time=self.clock()
        )
        limits = request.effective_limits
        budget = self.budget_factory(limits.timeout_ms)
        historical = "explicit_as_of" in arguments
        with self.reader.open(budget) as read:
            facts = read.spof_facts(
                request.important_targets,
                request.candidate_nodes,
                as_of=request.as_of,
                max_depth=limits.max_depth,
                max_nodes=limits.max_nodes,
                page_size=self.page_size,
                should_stop=lambda: budget.remaining() <= self.completion_reserve_ms / 1000,
            )
            evaluation = evaluate_spof_facts(facts, self.states, budget, historical=historical)
            response = build_spof_result(
                facts,
                evaluation,
                budget,
                max_paths=limits.max_paths,
                graph_generation=read.validation.generation,
                graph_observed_at=read.observed_at,
                as_of=request.as_of,
                historical=historical,
            )
            response.data["requested_limits"] = dict(request.requested_limits)
            response.data["effective_limits"] = asdict(limits)
            budget.require()
        return response
