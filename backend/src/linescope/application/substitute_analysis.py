"""Internal facts/state/decision composition; caller owns authorization/read gate.

No SQL, driver, HTTP or LLM dependency. Results must not be published until the
outer verified Graph read context exits successfully.
"""

from dataclasses import dataclass

from ..domain.canonical import normalize_uuid
from ..domain.graph_substitute_selection import (
    SubstituteSelection,
    select_substitutes_for_exclusion,
)
from .graph_availability import observe_availability
from .graph_request import ENTITY_TYPES


@dataclass(frozen=True)
class ObservedSubstituteEvaluation:
    selection: SubstituteSelection
    observation: dict
    missing_states: tuple


def evaluate_substitute_facts(facts, states, budget, *, historical, excluded=()):
    if type(historical) is not bool:
        raise ValueError("Explicit historical analysis mode is required")
    if type(excluded) not in (list, tuple, set, frozenset):
        raise ValueError("Typed exclusions are required")
    for node in excluded:
        if (
            type(node) is not tuple
            or len(node) != 2
            or type(node[0]) is not str
            or node[0] not in ENTITY_TYPES
            or type(node[1]) is not str
            or normalize_uuid(node[1]) != node[1]
        ):
            raise ValueError("Canonical typed exclusions are required")
    nodes = set(facts.prerequisites) | {facts.target} | set(facts.candidates)
    for dependencies in facts.prerequisites.values():
        nodes.update(dependencies)
    observation = observe_availability(nodes, states, budget)
    selection = select_substitutes_for_exclusion(
        facts.target,
        list(facts.candidates),
        facts.prerequisites,
        observation.values,
        complete=facts.complete,
        historical=historical,
        excluded=excluded,
    )
    budget.require()
    return ObservedSubstituteEvaluation(selection, observation.facts, observation.missing_states)
