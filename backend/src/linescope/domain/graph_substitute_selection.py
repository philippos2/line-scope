"""Aggregate direct substitute candidates for a hypothetical exclusion.

The caller verifies direct active/effective CAN_SUBSTITUTE edges and bounded
mandatory closures. This module neither discovers candidates nor follows chains.
"""

from dataclasses import dataclass

from .graph_reachability import Node
from .graph_requirement_rules import substitute_availability
from .graph_substitute_candidate import (
    SUBSTITUTE_TYPES,
    SubstituteCandidateEvaluation,
    evaluate_substitute_candidate,
)


@dataclass(frozen=True)
class EvaluatedSubstitute:
    node: Node
    evaluation: SubstituteCandidateEvaluation


@dataclass(frozen=True)
class SubstituteSelection:
    target: Node
    candidates: tuple[EvaluatedSubstitute, ...]
    availability: str
    complete: bool
    reason: str | None


def select_substitutes_for_exclusion(
    target: Node, candidates, prerequisites, availabilities, *, excluded=(), complete, historical
):
    """Exclude the original and evaluate each direct candidate independently.

    Other exclusions remain in force. Available candidates dominate unknown
    operational states, but incomplete closure or mandatory cycles never become
    definitive replacement guarantees. Empty means none only if complete.
    """
    if (
        type(target) is not tuple
        or len(target) != 2
        or any(type(value) is not str or not value for value in target)
        or target[0] not in SUBSTITUTE_TYPES
        or type(candidates) not in (list, tuple)
        or type(complete) is not bool
        or type(historical) is not bool
        or type(excluded) not in (list, tuple, set, frozenset)
    ):
        raise ValueError("Invalid substitution selection input")
    for candidate in candidates:
        if (
            type(candidate) is not tuple
            or len(candidate) != 2
            or any(type(value) is not str or not value for value in candidate)
            or candidate[0] != target[0]
            or candidate == target
        ):
            raise ValueError("Direct substitutes must be distinct same-type objects")
    # Validate even an empty candidate set using the same input boundary. The
    # target's result is discarded: selection does not evaluate the original.
    evaluate_substitute_candidate(
        target,
        prerequisites,
        availabilities,
        excluded=excluded,
        complete=complete,
        historical=historical,
    )
    exclusions = set(excluded) | {target}
    evaluated = tuple(
        EvaluatedSubstitute(
            node,
            evaluate_substitute_candidate(
                node,
                prerequisites,
                availabilities,
                excluded=exclusions,
                complete=complete,
                historical=historical,
            ),
        )
        for node in sorted(set(candidates))
    )
    reasons = {item.evaluation.reason for item in evaluated}
    if not complete or "INCOMPLETE" in reasons:
        return SubstituteSelection(target, evaluated, "UNKNOWN", False, "INCOMPLETE")
    if "MANDATORY_CYCLE" in reasons:
        return SubstituteSelection(target, evaluated, "UNKNOWN", True, "MANDATORY_CYCLE")
    availability = substitute_availability(
        [item.evaluation.availability for item in evaluated], complete=True
    )
    reason = "UNKNOWN_AVAILABILITY" if availability == "UNKNOWN" else None
    return SubstituteSelection(target, evaluated, availability, True, reason)
