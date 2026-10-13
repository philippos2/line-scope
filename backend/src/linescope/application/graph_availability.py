"""One authoritative state observation and validation for bounded Graph nodes."""

from dataclasses import dataclass
from datetime import datetime

from ..domain.canonical import normalize_uuid
from ..domain.graph_requirement_rules import equipment_availability, operation_availability
from .reads import ToolError


@dataclass(frozen=True)
class AvailabilityObservation:
    values: dict
    facts: dict
    missing_states: tuple


def observe_availability(nodes, states, budget):
    equipment_ids = sorted(node[1] for node in nodes if node[0] == "Equipment")
    operation_ids = sorted(node[1] for node in nodes if node[0] == "ProductionOperation")
    budget.require()
    observation = states.read_availability(equipment_ids, operation_ids, budget)
    availability = {}
    try:
        observed_at = observation["observed_at"]
        if (
            not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
        ):
            raise ValueError("Invalid observation time")
        for kind, field, id_field, state_field, requested, convert in (
            (
                "Equipment",
                "states",
                "equipment_id",
                "state_code",
                equipment_ids,
                equipment_availability,
            ),
            (
                "ProductionOperation",
                "operations",
                "production_operation_id",
                "planned_status",
                operation_ids,
                operation_availability,
            ),
        ):
            records = observation[field]
            if records is None:
                records = []
            if type(records) is not list:
                raise ValueError("Invalid state collection")
            for record in records:
                identifier = normalize_uuid(record[id_field])
                node = (kind, identifier)
                if (
                    identifier not in requested
                    or node in availability
                    or type(record["version"]) is not int
                    or record["version"] <= 0
                    or type(record[state_field]) is not str
                ):
                    raise ValueError("Invalid authoritative state fact")
                availability[node] = convert(record[state_field])
    except (KeyError, TypeError, ValueError) as error:
        raise ToolError("INTERNAL_ERROR", "Authoritative Graph states are inconsistent") from error
    budget.require()
    stateful = {node for node in nodes if node[0] in {"Equipment", "ProductionOperation"}}
    return AvailabilityObservation(
        availability, observation, tuple(sorted(stateful - availability.keys()))
    )
