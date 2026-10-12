"""Mandatory AND fulfillment after exclusion with evaluated direct replacements.

The caller supplies selections evaluated against the same exclusions, generation,
analysis mode and bounded facts. Replacement never waives another prerequisite.
This is a structural calculation, not an operational or SPOF determination.
"""

from collections import deque

from .graph_fulfillment import StructuralFulfillment, structural_fulfillment
from .graph_requirement_rules import AVAILABILITIES, required_availability
from .graph_substitute_selection import SubstituteSelection


def exclusion_fulfillment(target, prerequisites, replacements, *, excluded, complete):
    baseline = structural_fulfillment(target, prerequisites, excluded=excluded, complete=complete)
    if type(replacements) is not dict:
        raise ValueError("Evaluated replacements must be a map")
    excluded = set(excluded)
    for node, selection in replacements.items():
        if (
            node not in excluded
            or not isinstance(selection, SubstituteSelection)
            or selection.target != node
            or type(selection.availability) is not str
            or selection.availability not in AVAILABILITIES
            or type(selection.complete) is not bool
            or selection.reason
            not in (None, "INCOMPLETE", "MANDATORY_CYCLE", "UNKNOWN_AVAILABILITY")
            or (not selection.complete and selection.reason != "INCOMPLETE")
            or (selection.reason is not None and selection.availability != "UNKNOWN")
        ):
            raise ValueError("Invalid evaluated replacement")
    if baseline.determination == "INDETERMINATE":
        return baseline

    closure, pending = set(), [target]
    while pending:
        node = pending.pop()
        if node in closure:
            continue
        closure.add(node)
        pending.extend(prerequisites[node])
    used = [replacements[node] for node in closure & excluded if node in replacements]
    if any(not item.complete for item in used):
        return StructuralFulfillment("INDETERMINATE", "INCOMPLETE")
    if any(item.reason == "MANDATORY_CYCLE" for item in used):
        return StructuralFulfillment("INDETERMINATE", "MANDATORY_CYCLE")

    remaining, dependents = {}, {node: set() for node in closure}
    for node in closure:
        dependencies = set(prerequisites[node])
        remaining[node] = len(dependencies)
        for dependency in dependencies:
            dependents[dependency].add(node)
    ready = deque(node for node in closure if remaining[node] == 0)
    values = {}
    while ready:
        node = ready.popleft()
        if node in excluded:
            # Missing replacement evaluation is unknown, never proof of none.
            values[node] = replacements[node].availability if node in replacements else "UNKNOWN"
        else:
            values[node] = required_availability(
                [values[dependency] for dependency in prerequisites[node]], complete=True
            )
        for dependent in dependents[node]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    determination = {
        "AVAILABLE": "ESTABLISHED",
        "UNAVAILABLE": "NOT_ESTABLISHED",
        "UNKNOWN": "INDETERMINATE",
    }[values[target]]
    return StructuralFulfillment(
        determination, "UNKNOWN_REPLACEMENT" if determination == "INDETERMINATE" else None
    )
