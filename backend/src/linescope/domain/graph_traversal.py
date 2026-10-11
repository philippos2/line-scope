"""Logical traversal directions from domain-model §4, not stored edge direction."""

IMPACT_FORWARD = frozenset({"PRECEDES", "SUPPLIES", "CONTROLS", "PRODUCES"})
IMPACT_REVERSE = frozenset({"DEPENDS_ON", "USES"})


def traversal_types(direction):
    if direction == "IMPACT":
        return IMPACT_FORWARD, IMPACT_REVERSE
    if direction == "UPSTREAM":
        return IMPACT_REVERSE, IMPACT_FORWARD
    raise ValueError("Invalid Graph traversal direction")
