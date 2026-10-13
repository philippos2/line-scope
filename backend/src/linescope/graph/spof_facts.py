"""SPOF discovery and one-step replacement facts within one verified read.

Facts do not imply simultaneous candidate exclusion. Each candidate must later
be evaluated independently, using one authoritative state observation.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from ..application.reads import ToolError
from ..domain.graph_reachability import TraversalNodeBudget
from .alternative_facts import _roots, collect_alternative_facts


@dataclass(frozen=True)
class SpofAnalysisFacts:
    important_targets: tuple
    candidates_by_target: tuple
    prerequisites: dict
    target_searches: tuple
    substitutes: tuple
    dependency_edges: tuple
    complete: bool
    limit_reason: str | None


def collect_spof_facts(
    read,
    important_targets,
    candidate_nodes=None,
    *,
    as_of,
    max_depth,
    max_nodes,
    page_size,
    should_stop=None,
):
    targets = _roots(important_targets)
    if candidate_nodes is not None and type(candidate_nodes) not in (list, tuple):
        raise ValueError("Optional candidate collection is required")
    candidates = (
        None if candidate_nodes is None else _roots(candidate_nodes) if candidate_nodes else ()
    )
    for value in (max_depth, max_nodes, page_size):
        if type(value) is not int or value <= 0:
            raise ValueError("Positive server-owned limits are required")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Aware analysis time is required")
    budget = TraversalNodeBudget(max_nodes, roots=set(targets) | set(candidates or ()))
    for node in sorted(budget.nodes):
        registered = read.node(*node)
        if registered is None or not registered.active:
            raise ToolError("TARGET_NOT_FOUND", "All SPOF inputs must be active")
    closures = []
    for target in targets:
        closures.append(
            read.mandatory_closure(
                *target,
                as_of=as_of,
                max_depth=max_depth,
                max_nodes=max_nodes,
                page_size=min(page_size, max_nodes),
                should_stop=should_stop,
                node_budget=budget,
            )
        )
    groups = tuple(
        (
            target,
            tuple(
                sorted(
                    set(candidates) - {target}
                    if candidates is not None
                    else {item.node for item in closure.reachability.nodes} - {target}
                )
            ),
        )
        for target, closure in zip(targets, closures, strict=True)
    )
    selected = tuple(sorted({node for _, nodes in groups for node in nodes}))
    reasons = {
        item.reachability.limit_reason for item in closures if not item.reachability.complete
    }
    if selected:
        combined = collect_alternative_facts(
            read,
            targets,
            selected,
            as_of=as_of,
            max_depth=max_depth,
            max_nodes=max_nodes,
            page_size=page_size,
            should_stop=should_stop,
            node_budget=budget,
        )
        prerequisites, edges, searches, substitutes = (
            combined.prerequisites,
            combined.dependency_edges,
            combined.target_searches,
            combined.substitutes,
        )
        if not combined.complete:
            reasons.add(combined.limit_reason)
    else:
        prerequisites, records = {}, {}
        for closure in closures:
            for node, upstream in closure.prerequisites.items():
                prerequisites.setdefault(node, set()).update(
                    item for item in upstream if item in budget.nodes
                )
            for edge in closure.edges:
                if {
                    (edge["source_type"], edge["source_id"]),
                    (edge["target_type"], edge["target_id"]),
                } <= budget.nodes:
                    records[edge["source_record_id"]] = edge
        prerequisites = {
            node: tuple(sorted(values)) for node, values in sorted(prerequisites.items())
        }
        edges = tuple(records[key] for key in sorted(records))
        searches = tuple(
            (target, closure.reachability)
            for target, closure in zip(targets, closures, strict=True)
        )
        substitutes = ()
    reason = next((value for value in ("TIMEOUT", "NODE_COUNT", "DEPTH") if value in reasons), None)
    return SpofAnalysisFacts(
        targets,
        groups,
        prerequisites,
        searches,
        tuple(replace(item, complete=reason is None, limit_reason=reason) for item in substitutes),
        edges,
        reason is None,
        reason,
    )
