"""Server-built alternative DTO/Evidence from verified facts and evaluations.

No storage, HTTP or LLM. Caller owns authorization and successful Graph exit.
"""

from datetime import datetime

from ..domain.canonical import normalize_uuid
from ..domain.graph_traversal import IMPACT_FORWARD, IMPACT_REVERSE
from .fulfillment_evidence import _reason, _typed, collect_fulfillment_paths
from .graph_evidence import UNEVALUATED_DIMENSIONS
from .reads import ReadResult, json_value


def _determination(result, complete):
    return {
        "determination": result.determination if complete else "INDETERMINATE",
        "reason": _reason(result.reason) if complete else "INCOMPLETE_SEARCH",
    }


def build_alternative_result(
    facts,
    evaluation,
    budget,
    *,
    max_paths,
    graph_generation,
    graph_observed_at,
    as_of,
    historical,
):
    if type(max_paths) is not int or max_paths <= 0 or type(historical) is not bool:
        raise ValueError("Explicit server path limit and analysis mode are required")
    generation = normalize_uuid(graph_generation)
    for at in (graph_observed_at, as_of):
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Aware evidence timestamps are required")
    if (
        evaluation.historical != historical
        or len(evaluation.targets) != len(facts.important_targets)
        or len(evaluation.replacements) != len(facts.excluded_nodes)
        or any(
            item.excluded_nodes != frozenset(facts.excluded_nodes)
            for item in evaluation.replacements
        )
        or {item.target for item in evaluation.targets} != set(facts.important_targets)
        or {item.target for item in evaluation.replacements} != set(facts.excluded_nodes)
        or evaluation.complete != facts.complete
        or evaluation.limit_reason != facts.limit_reason
    ):
        raise ValueError("Evaluation must match collected analysis facts")
    budget.require()
    paths, mandatory, substitutions, omitted = collect_fulfillment_paths(facts, budget, max_paths)
    complete = facts.complete and not omitted
    reason = facts.limit_reason or ("PATH_COUNT" if omitted else None)
    targets = [
        {
            "important_target": _typed(item.target),
            "before": _determination(item.before, complete),
            "after": _determination(item.after, complete),
        }
        for item in evaluation.targets
    ]
    alternatives = []
    for selection in evaluation.replacements:
        alternatives.append(
            {
                "excluded_node": _typed(selection.target),
                "availability": selection.availability if complete else "UNKNOWN",
                "reason": _reason(selection.reason) if complete else "INCOMPLETE_SEARCH",
                "candidates": [
                    {
                        "candidate": _typed(item.node),
                        "availability": item.evaluation.availability if complete else "UNKNOWN",
                        "structure": _determination(item.evaluation.structure, complete),
                        "reason": _reason(item.evaluation.reason)
                        if complete
                        else "INCOMPLETE_SEARCH",
                    }
                    for item in selection.candidates
                ],
            }
        )
    indeterminate = (
        not complete
        or any(
            item["before"]["determination"] == "INDETERMINATE"
            or item["after"]["determination"] == "INDETERMINATE"
            for item in targets
        )
        or any(item["availability"] == "UNKNOWN" for item in alternatives)
    )
    mode = "EXPLICIT_HISTORICAL" if historical else "CURRENT"
    data = {
        "important_targets": [_typed(node) for node in facts.important_targets],
        "excluded_nodes": [_typed(node) for node in facts.excluded_nodes],
        "target_results": targets,
        "alternatives": alternatives,
        "representative_paths": paths,
        "complete": complete,
        "limit_reason": reason,
        "determination": "INDETERMINATE" if indeterminate else "DETERMINATE",
        "analysis_mode": mode,
        "analysis_scope": "DEPENDENCY_FULFILLMENT",
        "not_evaluated": list(UNEVALUATED_DIMENSIONS),
        "graph_sync_state": "CURRENT",
    }
    states, operations = (
        evaluation.observation["states"] or [],
        evaluation.observation["operations"] or [],
    )
    versions = {"Equipment:" + item["equipment_id"]: item["version"] for item in states}
    versions.update(
        {
            "ProductionOperation:" + item["production_operation_id"]: item["version"]
            for item in operations
        }
    )
    evidence = {
        "source": "NEO4J_AND_POSTGRESQL",
        "tool": "find_alternative_paths",
        "graph_generation": generation,
        "graph_observed_at": graph_observed_at,
        "as_of": as_of,
        "temporal_scope": "CURRENT_REGISTRATION_AT_AS_OF",
        "analysis_mode": mode,
        "analysis_scope": data["analysis_scope"],
        "not_evaluated": data["not_evaluated"],
        "relation_types": sorted(IMPACT_FORWARD | IMPACT_REVERSE | {"CAN_SUBSTITUTE"}),
        "representative_paths": paths,
        "mandatory_relations": mandatory,
        "substitution_relations": substitutions,
        "state_observed_at": evaluation.observation["observed_at"],
        "state_versions": versions,
        "current_states": states,
        "current_operation_states": operations,
        "missing_states": [_typed(node) for node in evaluation.missing_states],
        "state_temporal_scope": "CURRENT_STATE_AT_OBSERVATION",
    }
    budget.require()
    result = ReadResult(json_value(data), json_value(evidence))
    budget.require()
    return result
