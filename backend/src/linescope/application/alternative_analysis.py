"""Internal multi-target evaluation from one authoritative state observation.

The caller owns request authorization, verified Graph facts and the exit gate.
This returns structure and replacement availability, not operational guarantees.
"""

from dataclasses import dataclass

from ..domain.graph_exclusion_fulfillment import exclusion_fulfillment
from ..domain.graph_fulfillment import StructuralFulfillment, structural_fulfillment
from ..domain.graph_substitute_candidate import SUBSTITUTE_TYPES
from ..domain.graph_substitute_selection import (
    SubstituteSelection,
    select_substitutes_for_exclusion,
)
from .graph_availability import observe_availability


@dataclass(frozen=True)
class AlternativeTargetEvaluation:
    target: tuple
    before: StructuralFulfillment
    after: StructuralFulfillment


@dataclass(frozen=True)
class AlternativeEvaluation:
    targets: tuple[AlternativeTargetEvaluation, ...]
    replacements: tuple[SubstituteSelection, ...]
    observation: dict
    missing_states: tuple
    complete: bool
    limit_reason: str | None


def evaluate_alternative_facts(facts, states, budget, *, historical):
    if type(historical) is not bool:
        raise ValueError("Explicit historical analysis mode is required")
    if (
        len(facts.substitutes) != len(facts.excluded_nodes)
        or {item.target for item in facts.substitutes} != set(facts.excluded_nodes)
        or any(
            item.prerequisites != facts.prerequisites or item.complete != facts.complete
            for item in facts.substitutes
        )
    ):
        raise ValueError("Substitute facts must match the entire alternative analysis")
    nodes = set(facts.prerequisites) | set(facts.important_targets) | set(facts.excluded_nodes)
    for dependencies in facts.prerequisites.values():
        nodes.update(dependencies)
    for item in facts.substitutes:
        nodes.update(item.candidates)
    budget.require()
    observation = observe_availability(nodes, states, budget)
    replacements = {}
    for item in facts.substitutes:
        budget.require()
        if item.target[0] in SUBSTITUTE_TYPES:
            evaluated = select_substitutes_for_exclusion(
                item.target,
                list(item.candidates),
                facts.prerequisites,
                observation.values,
                excluded=facts.excluded_nodes,
                complete=facts.complete,
                historical=historical,
            )
        else:
            # Canonical relation endpoints prohibit substitutions for these types.
            if item.candidates or item.substitution_edges:
                raise ValueError("Unsupported substitution facts")
            evaluated = SubstituteSelection(
                item.target,
                frozenset(facts.excluded_nodes),
                (),
                "UNAVAILABLE" if facts.complete else "UNKNOWN",
                facts.complete,
                None if facts.complete else "INCOMPLETE",
            )
        replacements[item.target] = evaluated
    results = []
    for target in sorted(facts.important_targets):
        budget.require()
        before = structural_fulfillment(target, facts.prerequisites, complete=facts.complete)
        after = exclusion_fulfillment(
            target,
            facts.prerequisites,
            replacements,
            excluded=facts.excluded_nodes,
            complete=facts.complete,
        )
        results.append(AlternativeTargetEvaluation(target, before, after))
    budget.require()
    return AlternativeEvaluation(
        tuple(results),
        tuple(replacements[key] for key in sorted(replacements)),
        observation.facts,
        observation.missing_states,
        facts.complete,
        facts.limit_reason,
    )
