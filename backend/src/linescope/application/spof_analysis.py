"""Independent candidate exclusions from one authoritative state observation.

The caller owns authorization, bounded facts and the final Graph read gate.
Internal determinations are structural, not capacity or safety guarantees.
"""

from dataclasses import dataclass

from ..domain.graph_spof import SpofCandidateEvaluation, evaluate_spof_candidate
from ..domain.graph_substitute_candidate import SUBSTITUTE_TYPES
from ..domain.graph_substitute_selection import (
    SubstituteSelection,
    select_substitutes_for_exclusion,
)
from .graph_availability import observe_availability


@dataclass(frozen=True)
class SpofEvaluation:
    historical: bool
    findings: tuple[SpofCandidateEvaluation, ...]
    replacements: tuple[SubstituteSelection, ...]
    observation: dict
    missing_states: tuple
    complete: bool
    limit_reason: str | None


def evaluate_spof_facts(facts, states, budget, *, historical):
    if type(historical) is not bool:
        raise ValueError("Explicit historical analysis mode is required")
    groups = dict(facts.candidates_by_target)
    candidates = {candidate for _, nodes in facts.candidates_by_target for candidate in nodes}
    if (
        len(groups) != len(facts.candidates_by_target)
        or set(groups) != set(facts.important_targets)
        or any(target in nodes or len(set(nodes)) != len(nodes) for target, nodes in groups.items())
        or len(facts.substitutes) != len(candidates)
        or {item.target for item in facts.substitutes} != candidates
        or any(
            item.prerequisites != facts.prerequisites
            or item.complete != facts.complete
            or item.limit_reason != facts.limit_reason
            for item in facts.substitutes
        )
    ):
        raise ValueError("Candidate facts must match the whole SPOF analysis")
    nodes = set(facts.prerequisites) | set(facts.important_targets) | candidates
    for dependencies in facts.prerequisites.values():
        nodes.update(dependencies)
    for item in facts.substitutes:
        nodes.update(item.candidates)
        if item.target[0] not in SUBSTITUTE_TYPES and (item.candidates or item.substitution_edges):
            raise ValueError("Unsupported substitution facts")
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
                excluded=(item.target,),
                complete=facts.complete,
                historical=historical,
            )
        else:
            evaluated = SubstituteSelection(
                item.target,
                frozenset({item.target}),
                (),
                "UNAVAILABLE" if facts.complete else "UNKNOWN",
                facts.complete,
                None if facts.complete else "INCOMPLETE",
            )
        replacements[item.target] = evaluated
    findings = []
    for target in sorted(groups):
        for candidate in sorted(groups[target]):
            budget.require()
            findings.append(
                evaluate_spof_candidate(
                    target,
                    candidate,
                    facts.prerequisites,
                    replacements[candidate],
                    complete=facts.complete,
                )
            )
    budget.require()
    return SpofEvaluation(
        historical,
        tuple(findings),
        tuple(replacements[key] for key in sorted(replacements)),
        observation.facts,
        observation.missing_states,
        facts.complete,
        facts.limit_reason,
    )
