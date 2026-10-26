"""Required-edge and availability primitives, not a Graph/SPOF evaluator.

The caller supplies active, effective, validated relations and PostgreSQL state.
No authority, capacity, safety, cyclic fulfillment or substitution closure is
inferred. Product has no operational-state rule here. Process operational availability remains UNKNOWN. Infrastructure uses its
separate registered supply state, independently of structural reachability.
"""

FLAG_REQUIRED_RELATIONS = frozenset({"DEPENDS_ON", "SUPPLIES"})
INTRINSIC_REQUIRED_RELATIONS = frozenset({"PRECEDES", "CONTROLS", "PRODUCES"})
SUPPORTED_RELATIONS = (
    FLAG_REQUIRED_RELATIONS | INTRINSIC_REQUIRED_RELATIONS | {"USES", "CAN_SUBSTITUTE"}
)

AVAILABILITIES = frozenset({"AVAILABLE", "UNAVAILABLE", "UNKNOWN"})
EQUIPMENT_AVAILABILITY = {
    "RUNNING": "AVAILABLE",
    "STOPPED": "UNAVAILABLE",
    "UNDER_MAINTENANCE": "UNAVAILABLE",
    "UNKNOWN": "UNKNOWN",
}
OPERATION_AVAILABILITY = {"PLANNED": "AVAILABLE", "CANCELLED": "UNAVAILABLE"}


def required_dependency(relation_type, required=None):
    """Intrinsic USES cannot be made optional by a missing/false derived flag."""
    if type(relation_type) is not str or relation_type not in SUPPORTED_RELATIONS:
        raise ValueError("Unknown dependency relation type")
    if relation_type == "USES":
        if required is not None and type(required) is not bool:
            raise ValueError("Invalid derived USES flag")
        return True
    if type(required) is not bool:
        raise ValueError("Canonical relation required must be boolean")
    if relation_type in FLAG_REQUIRED_RELATIONS:
        return required
    if required:
        raise ValueError("This relation does not use the required field")
    return relation_type in INTRINSIC_REQUIRED_RELATIONS


def _state_availability(state, mapping):
    if state is None:
        return "UNKNOWN"
    if type(state) is not str or state not in mapping:
        raise ValueError("Invalid canonical operational state")
    return mapping[state]


def equipment_availability(state_code):
    return _state_availability(state_code, EQUIPMENT_AVAILABILITY)


def operation_availability(planned_status):
    """Planned availability, never a claim that an operation is executing."""
    return _state_availability(planned_status, OPERATION_AVAILABILITY)


def _inputs(values, complete):
    if type(complete) is not bool:
        raise ValueError("Input completeness must be explicit boolean")
    if type(values) not in (list, tuple) or any(
        type(value) is not str or value not in AVAILABILITIES for value in values
    ):
        raise ValueError("Availability values must be validated three-valued states")


def required_availability(values, *, complete):
    """AND over supplied prerequisites; empty is the logical neutral element.

    This does not replace the object's own operational-state check. Incomplete
    membership never becomes a definitive business evaluation.
    """
    _inputs(values, complete)
    if not complete:
        return "UNKNOWN"
    if "UNAVAILABLE" in values:
        return "UNAVAILABLE"
    return "UNKNOWN" if "UNKNOWN" in values else "AVAILABLE"


def substitute_availability(values, *, complete):
    """OR over independently evaluated one-step candidates, not relation existence.

    The caller owes each candidate's own required conditions, exclusions and
    cycle checks. Never feed a CAN_SUBSTITUTE relation as AVAILABLE itself.
    """
    _inputs(values, complete)
    if not complete:
        return "UNKNOWN"
    if "AVAILABLE" in values:
        return "AVAILABLE"
    return "UNKNOWN" if "UNKNOWN" in values else "UNAVAILABLE"


def infrastructure_availability(state):
    """Registered supply condition; absent records never imply available supply."""
    if state is None:
        return "UNKNOWN"
    if state not in AVAILABILITIES:
        raise ValueError("Invalid infrastructure supply state")
    return state
