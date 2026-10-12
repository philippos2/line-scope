"""Bounded one-step substitute facts inside an already verified read context.

No authorization, state lookup or public DTOs. The caller publishes only after
successful reader exit and evaluates availability from PostgreSQL separately.
"""

from dataclasses import dataclass

from ..domain.canonical import normalize_uuid
from ..domain.graph_reachability import Node, Reachability, TraversalNodeBudget
from ..domain.graph_substitute_candidate import SUBSTITUTE_TYPES


@dataclass(frozen=True)
class SubstituteAnalysisFacts:
    target: Node
    candidates: tuple[Node, ...]
    prerequisites: dict
    searches: tuple[tuple[Node, Reachability], ...]
    dependency_edges: tuple[dict, ...]
    substitution_edges: tuple[dict, ...]
    complete: bool
    limit_reason: str | None


def collect_substitute_facts(
    read, target, *, as_of, max_depth, max_nodes, page_size, should_stop=None, node_budget=None
):
    if (
        type(target) is not tuple
        or len(target) != 2
        or type(target[0]) is not str
        or target[0] not in SUBSTITUTE_TYPES
    ):
        raise ValueError("A typed substitute target is required")
    target = (target[0], normalize_uuid(target[1]))
    for limit in (max_depth, max_nodes, page_size):
        if type(limit) is not int or limit <= 0:
            raise ValueError("Positive server-owned fact limits are required")
    if node_budget is None:
        node_budget = TraversalNodeBudget(max_nodes, roots=(target,))
    if (
        not isinstance(node_budget, TraversalNodeBudget)
        or node_budget.max_nodes != max_nodes
        or not node_budget.admit(target)
    ):
        raise ValueError("Shared budget must admit the target and match the node limit")
    candidates, dependencies, substitutions, prerequisites, searches, reasons = (
        set(),
        {},
        {},
        {},
        [],
        set(),
    )

    def collect_closure(node):
        result = read.mandatory_closure(
            *node,
            as_of=as_of,
            max_depth=max_depth,
            max_nodes=max_nodes,
            page_size=min(page_size, max_nodes),
            should_stop=should_stop,
            node_budget=node_budget,
        )
        searches.append((node, result.reachability))
        if not result.reachability.complete:
            reasons.add(result.reachability.limit_reason)
        for dependent, upstream in result.prerequisites.items():
            prerequisites.setdefault(dependent, set()).update(
                item for item in upstream if item in node_budget.nodes
            )
        for edge in result.edges:
            endpoints = {
                (edge["source_type"], edge["source_id"]),
                (edge["target_type"], edge["target_id"]),
            }
            if endpoints <= node_budget.nodes:
                dependencies[edge["source_record_id"]] = edge

    collect_closure(target)
    after = None
    stopped = False
    while True:
        if should_stop is not None and should_stop():
            reasons.add("TIMEOUT")
            break
        page = read.substitute_candidates(
            *target,
            as_of=as_of,
            limit=min(page_size, max_nodes),
            after=after,
        )
        for edge in page.edges:
            if should_stop is not None and should_stop():
                reasons.add("TIMEOUT")
                stopped = True
                break
            candidate = (edge["source_type"], edge["source_id"])
            if candidate == target:
                continue  # The excluded original cannot replace itself.
            if not node_budget.admit(candidate):
                reasons.add("NODE_COUNT")
                stopped = True
                break
            substitutions[edge["source_record_id"]] = edge
            if candidate not in candidates:
                candidates.add(candidate)
                collect_closure(candidate)
        if stopped or not page.has_more:
            break
        last = page.edges[-1]
        after = (last["neighbor_type"], last["neighbor_id"], last["source_record_id"])
    reason = next((value for value in ("TIMEOUT", "NODE_COUNT", "DEPTH") if value in reasons), None)
    return SubstituteAnalysisFacts(
        target,
        tuple(sorted(candidates)),
        {node: tuple(sorted(values)) for node, values in sorted(prerequisites.items())},
        tuple(searches),
        tuple(dependencies[key] for key in sorted(dependencies)),
        tuple(substitutions[key] for key in sorted(substitutions)),
        reason is None,
        reason,
    )
