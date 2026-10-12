"""Pure mandatory-dependency structure evaluation, without substitution.

The caller supplies a bounded, active/as_of-filtered prerequisite graph whose
edges are classified with required_dependency. No availability, authority,
capacity, safety or SPOF claim is made. Missing closure is not a source node.
"""

from collections import deque
from dataclasses import dataclass

from .graph_reachability import Node


@dataclass(frozen=True)
class StructuralFulfillment:
    determination: str
    reason: str | None


def _node(node):
    if (
        type(node) is not tuple
        or len(node) != 2
        or any(type(value) is not str or not value for value in node)
    ):
        raise ValueError("A typed node is required")


def structural_fulfillment(target: Node, prerequisites, *, excluded=(), complete):
    """Evaluate only the target's mandatory closure, including excluded nodes.

    A mandatory cycle takes precedence over exclusion. An incomplete closure
    never yields a definitive determination. Iterative traversal handles long
    chains without depending on Python's recursion limit.
    """
    _node(target)
    if type(complete) is not bool or type(prerequisites) is not dict:
        raise ValueError("Explicit completeness and a prerequisite map are required")
    if type(excluded) not in (list, tuple, set, frozenset):
        raise ValueError("Excluded nodes must be a collection")
    for node in excluded:
        _node(node)
    excluded = set(excluded)
    for node, dependencies in prerequisites.items():
        _node(node)
        if type(dependencies) not in (list, tuple, set, frozenset):
            raise ValueError("Prerequisites must be a node collection")
        for dependency in dependencies:
            _node(dependency)
    if not complete:
        return StructuralFulfillment("INDETERMINATE", "INCOMPLETE")

    closure, pending = set(), [target]
    while pending:
        node = pending.pop()
        if node in closure:
            continue
        if node not in prerequisites:
            return StructuralFulfillment("INDETERMINATE", "INCOMPLETE")
        closure.add(node)
        pending.extend(prerequisites[node])

    remaining, dependents = {}, {node: set() for node in closure}
    for node in closure:
        dependencies = set(prerequisites[node])
        remaining[node] = len(dependencies)
        for dependency in dependencies:
            dependents[dependency].add(node)
    ready = deque(node for node in closure if remaining[node] == 0)
    established, visited = {}, 0
    while ready:
        node = ready.popleft()
        visited += 1
        established[node] = node not in excluded and all(
            established[dependency] for dependency in prerequisites[node]
        )
        for dependent in dependents[node]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    if visited != len(closure):
        return StructuralFulfillment("INDETERMINATE", "MANDATORY_CYCLE")
    return StructuralFulfillment("ESTABLISHED" if established[target] else "NOT_ESTABLISHED", None)
