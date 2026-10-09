"""Pure validation of a complete final PostgreSQL relation/assignment set.

Callers must supply consistent full business rows after applying every target.
This does not collect/lock rows, check endpoint existence, or certify Graph state.
"""

from collections import deque

from .assignments import _record as assignment_record
from .relations import _record as relation_record


class DependencyCycleError(ValueError):
    """A valid final row set contains a prohibited structural cycle."""


def validate_dependency_cycles(relations, assignments):
    """Reject structural cycles, regardless of effective periods or required.

    Nodes are typed IDs. DEPENDS_ON and derived USES retain storage direction;
    PRECEDES and CONTROLS reverse it to the common upstream dependency direction.
    SUPPLIES, CAN_SUBSTITUTE and terminal PRODUCES do not participate.
    """
    if type(relations) is not list or type(assignments) is not list:
        raise ValueError("Complete relation and assignment arrays are required")
    adjacency = {}
    incoming = {}

    def edge(source, target):
        adjacency.setdefault(source, set())
        adjacency.setdefault(target, set())
        incoming.setdefault(source, 0)
        incoming.setdefault(target, 0)
        if target not in adjacency[source]:
            adjacency[source].add(target)
            incoming[target] += 1

    seen = set()
    for value in relations:
        row = relation_record(value)
        identifier = row["dependency_relation_id"]
        if identifier in seen:
            raise ValueError("Duplicate relation row")
        seen.add(identifier)
        kind = row["relation_type"]
        if not row["active"] or kind not in {"DEPENDS_ON", "PRECEDES", "CONTROLS"}:
            continue
        source = (row["source_entity_type"], row["source_entity_id"])
        target = (row["target_entity_type"], row["target_entity_id"])
        if kind in {"PRECEDES", "CONTROLS"}:
            source, target = target, source
        edge(source, target)
    seen = set()
    for value in assignments:
        row = assignment_record(value)
        identifier = row["assignment_id"]
        if identifier in seen:
            raise ValueError("Duplicate assignment row")
        seen.add(identifier)
        if row["active"]:
            edge(
                ("ProductionOperation", row["production_operation_id"]),
                ("Equipment", row["equipment_id"]),
            )
    # Iterative topological elimination handles long chains without recursion.
    ready = deque(node for node, count in incoming.items() if count == 0)
    removed = 0
    while ready:
        node = ready.popleft()
        removed += 1
        for target in adjacency[node]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if removed != len(incoming):
        raise DependencyCycleError("Prohibited structural dependency cycle")
