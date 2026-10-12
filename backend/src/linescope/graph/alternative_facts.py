"""Multi-target alternative facts under the caller's verified read context.

No authority or state inference. The caller must validate the Tool request and
publish only after reader exit. All input roots share one distinct-node budget.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from ..application.reads import ToolError
from ..domain.canonical import normalize_uuid
from ..domain.graph_reachability import TraversalNodeBudget
from ..domain.graph_substitute_candidate import SUBSTITUTE_TYPES
from .neo4j_generation import NODE_TYPES
from .neo4j_projection import ProjectionIntegrityError
from .substitute_facts import SubstituteAnalysisFacts, collect_substitute_facts


@dataclass(frozen=True)
class AlternativeAnalysisFacts:
    important_targets: tuple
    excluded_nodes: tuple
    prerequisites: dict
    target_searches: tuple
    substitutes: tuple[SubstituteAnalysisFacts, ...]
    dependency_edges: tuple[dict, ...]
    complete: bool
    limit_reason: str | None


def _roots(values):
    if type(values) not in (list, tuple) or not values:
        raise ValueError("Nonempty typed input sets are required")
    nodes = []
    for node in values:
        if (
            type(node) is not tuple
            or len(node) != 2
            or type(node[0]) is not str
            or node[0] not in NODE_TYPES
            or type(node[1]) is not str
        ):
            raise ValueError("Typed input nodes are required")
        nodes.append((node[0], normalize_uuid(node[1])))
    if len(set(nodes)) != len(nodes):
        raise ValueError("Distinct nodes are required within each input set")
    return tuple(sorted(nodes))


def collect_alternative_facts(
    read,
    important_targets,
    excluded_nodes,
    *,
    as_of,
    max_depth,
    max_nodes,
    page_size,
    should_stop=None,
):
    targets, excluded = _roots(important_targets), _roots(excluded_nodes)
    for limit in (max_depth, max_nodes, page_size):
        if type(limit) is not int or limit <= 0:
            raise ValueError("Positive server-owned analysis limits are required")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("An aware analysis time is required")
    roots = set(targets) | set(excluded)
    budget = TraversalNodeBudget(max_nodes, roots=roots)
    for node in sorted(roots):
        registered = read.node(*node)
        if registered is None or not registered.active:
            raise ToolError("TARGET_NOT_FOUND", "All alternative analysis inputs must be active")
    prerequisites, records, searches, substitutes, reasons = {}, {}, [], [], set()

    def merge(prerequisite_map, edges):
        for node, dependencies in prerequisite_map.items():
            prerequisites.setdefault(node, set()).update(
                item for item in dependencies if item in budget.nodes
            )
        for edge in edges:
            endpoints = {
                (edge["source_type"], edge["source_id"]),
                (edge["target_type"], edge["target_id"]),
            }
            if not endpoints <= budget.nodes:
                continue
            identifier = edge["source_record_id"]
            if identifier in records and records[identifier] != edge:
                raise ProjectionIntegrityError("Conflicting mandatory relation facts")
            records[identifier] = edge

    def closure(node):
        result = read.mandatory_closure(
            *node,
            as_of=as_of,
            max_depth=max_depth,
            max_nodes=max_nodes,
            page_size=min(page_size, max_nodes),
            should_stop=should_stop,
            node_budget=budget,
        )
        merge(result.prerequisites, result.edges)
        if not result.reachability.complete:
            reasons.add(result.reachability.limit_reason)
        return result

    for node in targets:
        searches.append((node, closure(node).reachability))
    for node in excluded:
        if node[0] in SUBSTITUTE_TYPES:
            result = collect_substitute_facts(
                read,
                node,
                as_of=as_of,
                max_depth=max_depth,
                max_nodes=max_nodes,
                page_size=min(page_size, max_nodes),
                should_stop=should_stop,
                node_budget=budget,
            )
            merge(result.prerequisites, result.dependency_edges)
            if not result.complete:
                reasons.add(result.limit_reason)
        else:
            # The canonical endpoint model provides no substitution relation
            # for Product or ProductionOperation. Still collect their closure.
            captured = closure(node)
            result = SubstituteAnalysisFacts(
                node,
                (),
                captured.prerequisites,
                ((node, captured.reachability),),
                captured.edges,
                (),
                captured.reachability.complete,
                captured.reachability.limit_reason,
            )
        substitutes.append(result)
    reason = next((value for value in ("TIMEOUT", "NODE_COUNT", "DEPTH") if value in reasons), None)
    combined = {node: tuple(sorted(values)) for node, values in sorted(prerequisites.items())}
    return AlternativeAnalysisFacts(
        targets,
        excluded,
        combined,
        tuple(searches),
        tuple(
            replace(item, prerequisites=combined, complete=reason is None, limit_reason=reason)
            for item in substitutes
        ),
        tuple(records[key] for key in sorted(records)),
        reason is None,
        reason,
    )
