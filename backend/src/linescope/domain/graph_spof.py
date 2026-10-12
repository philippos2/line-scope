"""Per-target SPOF candidate classification over validated mandatory facts.

The caller owns bounded graph/selection reads, current-generation checks and
operational-state evidence. Classification does not infer capacity or safety.
"""

from dataclasses import dataclass

from .graph_exclusion_fulfillment import exclusion_fulfillment
from .graph_fulfillment import StructuralFulfillment, structural_fulfillment
from .graph_reachability import Node
from .graph_substitute_selection import SubstituteSelection


@dataclass(frozen=True)
class SpofCandidateEvaluation:
    target: Node
    candidate: Node
    determination: str
    reason: str | None
    before: StructuralFulfillment
    after: StructuralFulfillment | None


def evaluate_spof_candidate(
    target, candidate, prerequisites, replacement, *, complete, baseline_excluded=()
):
    """Exclude exactly one additional mandatory ancestor of the target.

    The replacement must have been evaluated with baseline exclusions plus the
    candidate. Missing evaluation is UNKNOWN. A pre-existing failure cannot be
    attributed to this exclusion. The target itself is never a SPOF candidate.
    """
    if (
        type(candidate) is not tuple
        or len(candidate) != 2
        or any(type(value) is not str or not value for value in candidate)
        or candidate == target
    ):
        raise ValueError("A distinct typed upstream candidate is required")
    before = structural_fulfillment(
        target, prerequisites, excluded=baseline_excluded, complete=complete
    )
    if replacement is not None and (
        not isinstance(replacement, SubstituteSelection) or replacement.target != candidate
    ):
        raise ValueError("Replacement evaluation must match the candidate")
    if before.determination != "ESTABLISHED":
        reason = before.reason or "BASELINE_NOT_ESTABLISHED"
        return SpofCandidateEvaluation(target, candidate, "INDETERMINATE", reason, before, None)

    closure, pending = set(), [target]
    while pending:
        node = pending.pop()
        if node in closure:
            continue
        closure.add(node)
        pending.extend(prerequisites[node])
    if candidate not in closure:
        return SpofCandidateEvaluation(
            target, candidate, "NOT_SPOF", "NOT_MANDATORY_UPSTREAM", before, None
        )
    after = exclusion_fulfillment(
        target,
        prerequisites,
        {} if replacement is None else {candidate: replacement},
        excluded=set(baseline_excluded) | {candidate},
        complete=complete,
    )
    determination = {
        "ESTABLISHED": "NOT_SPOF",
        "NOT_ESTABLISHED": "SPOF",
        "INDETERMINATE": "INDETERMINATE",
    }[after.determination]
    return SpofCandidateEvaluation(target, candidate, determination, after.reason, before, after)
