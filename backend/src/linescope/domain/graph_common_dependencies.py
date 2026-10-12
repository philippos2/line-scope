"""Common upstream candidates with proof paths from each distinct target.

Pure selection only. The caller owns authorization, bounded upstream traversal,
active/as_of filtering, one verified generation and the overall read deadline.
No failure, required-dependency, availability or SPOF determination is inferred.
"""

from dataclasses import dataclass

from .graph_paths import RepresentativePath, representative_paths
from .graph_reachability import Node, Reachability

LIMIT_PRIORITY = ("TIMEOUT", "NODE_COUNT", "DEPTH", "PATH_COUNT")


@dataclass(frozen=True)
class TargetPath:
    target: Node
    path: RepresentativePath


@dataclass(frozen=True)
class CommonDependency:
    candidate: Node
    paths: tuple[TargetPath, ...]


@dataclass(frozen=True)
class CommonDependencies:
    candidates: tuple[CommonDependency, ...]
    complete: bool
    limit_reason: str | None


def common_dependencies(searches, *, max_paths):
    """Intersect non-root reachability; never publish a candidate without all paths.

    searches is a sequence of (target, Reachability) pairs. Each target owns an
    already bounded upstream BFS. All representative paths for one candidate
    consume the shared output path budget together. Incomplete inputs can prove
    positive candidates, but an empty result is not proof that none exist.
    """
    if type(max_paths) is not int or max_paths <= 0:
        raise ValueError("Path limit must be a positive integer")
    if type(searches) not in (list, tuple) or len(searches) < 2:
        raise ValueError("At least two upstream searches are required")
    targets, by_target, reasons = set(), {}, set()
    for target, reachability in searches:
        if (
            type(target) is not tuple
            or len(target) != 2
            or any(type(item) is not str or not item for item in target)
            or target in targets
            or not isinstance(reachability, Reachability)
        ):
            raise ValueError("Distinct typed targets and upstream results are required")
        if (
            type(reachability.complete) is not bool
            or (
                reachability.limit_reason is not None
                and reachability.limit_reason not in LIMIT_PRIORITY
            )
            or reachability.complete != (reachability.limit_reason is None)
        ):
            raise ValueError("Invalid upstream completeness")
        roots = [item.node for item in reachability.nodes if item.distance == 0]
        if roots != [target]:
            raise ValueError("Upstream root must match its target")
        selection = representative_paths(reachability, max_paths=max(1, len(reachability.nodes)))
        by_target[target] = {path.nodes[-1]: path for path in selection.paths}
        targets.add(target)
        if selection.limit_reason:
            reasons.add(selection.limit_reason)
    ordered_targets = sorted(targets)
    common = set.intersection(*(set(by_target[target]) for target in ordered_targets))
    candidates = []
    for node in sorted(common):
        if (len(candidates) + 1) * len(targets) > max_paths:
            reasons.add("PATH_COUNT")
            break
        candidates.append(
            CommonDependency(
                node,
                tuple(TargetPath(target, by_target[target][node]) for target in ordered_targets),
            )
        )
    reason = next((item for item in LIMIT_PRIORITY if item in reasons), None)
    return CommonDependencies(tuple(candidates), reason is None, reason)
