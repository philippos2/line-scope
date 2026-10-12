"""One candidate's mandatory closure, without recursive substitution.

The caller verifies an active/effective direct CAN_SUBSTITUTE relation, supplies
bounded mandatory prerequisites and PostgreSQL-derived availability. This pure
calculation cannot discover replacements or infer capacity/safety guarantees.
"""

from dataclasses import dataclass

from .graph_fulfillment import StructuralFulfillment, structural_fulfillment
from .graph_reachability import Node
from .graph_requirement_rules import AVAILABILITIES, required_availability

SUBSTITUTE_TYPES = frozenset({"Equipment", "Process", "InfrastructureResource"})
STATEFUL_TYPES = frozenset({"Equipment", "ProductionOperation"})


@dataclass(frozen=True)
class SubstituteCandidateEvaluation:
    structure: StructuralFulfillment
    availability: str
    reason: str | None


def evaluate_substitute_candidate(
    candidate: Node, prerequisites, availabilities, *, excluded=(), complete, historical
):
    """Require every mandatory prerequisite without substituting any of them.

    Missing operational facts remain UNKNOWN. Process/InfrastructureResource
    lack authoritative operational states in v1; Product has no operational
    rule here. Historical availability is never inferred from current values.
    """
    structure = structural_fulfillment(
        candidate, prerequisites, excluded=excluded, complete=complete
    )
    if candidate[0] not in SUBSTITUTE_TYPES:
        raise ValueError("Unsupported substitute candidate type")
    if type(historical) is not bool or type(availabilities) is not dict:
        raise ValueError("Explicit analysis mode and availability map are required")
    for node, value in availabilities.items():
        if (
            type(node) is not tuple
            or len(node) != 2
            or any(type(item) is not str or not item for item in node)
            or type(value) is not str
            or value not in AVAILABILITIES
        ):
            raise ValueError("Invalid typed operational availability")
    if structure.determination == "INDETERMINATE":
        return SubstituteCandidateEvaluation(structure, "UNKNOWN", structure.reason)
    if structure.determination == "NOT_ESTABLISHED":
        return SubstituteCandidateEvaluation(structure, "UNAVAILABLE", "EXCLUDED_DEPENDENCY")

    closure, pending = set(), [candidate]
    while pending:
        node = pending.pop()
        if node in closure:
            continue
        closure.add(node)
        pending.extend(prerequisites[node])
    values = [
        availabilities.get(node, "UNKNOWN")
        if not historical and node[0] in STATEFUL_TYPES
        else "UNKNOWN"
        for node in closure
    ]
    availability = required_availability(values, complete=True)
    reason = {
        "AVAILABLE": None,
        "UNAVAILABLE": "UNAVAILABLE_DEPENDENCY",
        "UNKNOWN": "UNKNOWN_AVAILABILITY",
    }[availability]
    return SubstituteCandidateEvaluation(structure, availability, reason)
