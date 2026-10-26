"""SPOF public result from verified collection and independent exclusions."""

from datetime import datetime

from ..domain.canonical import normalize_uuid
from ..domain.graph_fulfillment import structural_fulfillment
from ..domain.graph_traversal import IMPACT_FORWARD, IMPACT_REVERSE
from .fulfillment_evidence import _reason, _typed, collect_fulfillment_paths
from .graph_evidence import UNEVALUATED_DIMENSIONS
from .reads import ReadResult, json_value


def build_spof_result(
    facts, evaluation, budget, *, max_paths, graph_generation, graph_observed_at, as_of, historical
):
    if type(max_paths) is not int or max_paths <= 0 or type(historical) is not bool:
        raise ValueError("Explicit path limit and analysis mode are required")
    generation = normalize_uuid(graph_generation)
    for at in (graph_observed_at, as_of):
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Aware evidence times are required")
    expected = {
        (target, candidate) for target, nodes in facts.candidates_by_target for candidate in nodes
    }
    actual = {(item.target, item.candidate) for item in evaluation.findings}
    candidates = {candidate for _, candidate in expected}
    if (
        evaluation.historical != historical
        or {target for target, _ in facts.candidates_by_target} != set(facts.important_targets)
        or actual != expected
        or len(evaluation.findings) != len(expected)
        or {item.target for item in evaluation.replacements} != candidates
        or len(evaluation.replacements) != len(candidates)
        or any(item.excluded_nodes != frozenset({item.target}) for item in evaluation.replacements)
        or evaluation.complete != facts.complete
        or evaluation.limit_reason != facts.limit_reason
    ):
        raise ValueError("Evaluation must match independent candidate exclusions")
    budget.require()
    paths, mandatory, substitutions, omitted = collect_fulfillment_paths(facts, budget, max_paths)
    complete = facts.complete and not omitted
    reason = facts.limit_reason or ("PATH_COUNT" if omitted else None)
    replacements = {item.target: item for item in evaluation.replacements}
    findings = []
    mapping = {"SPOF": "CANDIDATE", "NOT_SPOF": "NOT_CANDIDATE", "INDETERMINATE": "INDETERMINATE"}
    for item in evaluation.findings:
        budget.require()
        selection = replacements[item.candidate]
        findings.append(
            {
                "important_target": _typed(item.target),
                "candidate": _typed(item.candidate),
                "determination": mapping[item.determination] if complete else "INDETERMINATE",
                "reasons": ([_reason(item.reason)] if item.reason else [])
                if complete
                else ["INCOMPLETE_SEARCH"],
                "paths": [
                    path
                    for path in paths
                    if path["root"] in (_typed(item.target), _typed(item.candidate))
                ],
                "alternatives": {
                    "availability": selection.availability if complete else "UNKNOWN",
                    "reason": _reason(selection.reason) if complete else "INCOMPLETE_SEARCH",
                    "candidates": [
                        {
                            "candidate": _typed(candidate.node),
                            "availability": candidate.evaluation.availability
                            if complete
                            else "UNKNOWN",
                            "reason": _reason(candidate.evaluation.reason)
                            if complete
                            else "INCOMPLETE_SEARCH",
                        }
                        for candidate in selection.candidates
                    ],
                },
            }
        )
    mode = "EXPLICIT_HISTORICAL" if historical else "CURRENT"
    data = {
        "important_targets": [_typed(node) for node in facts.important_targets],
        "findings": findings,
        "representative_paths": paths,
        "complete": complete,
        "limit_reason": reason,
        "determination": "INDETERMINATE"
        if not complete
        or any(item["determination"] == "INDETERMINATE" for item in findings)
        or any(
            structural_fulfillment(target, facts.prerequisites, complete=complete).determination
            != "ESTABLISHED"
            for target in facts.important_targets
        )
        else "DETERMINATE",
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
    resources = evaluation.observation.get("resources") or []
    resources = [
        {
            **item,
            "record_reference": {
                "infrastructure_resource_id": item["infrastructure_resource_id"],
                "version": item["version"],
            },
        }
        for item in resources
    ]
    versions.update(
        {
            "InfrastructureResource:" + item["infrastructure_resource_id"]: item["version"]
            for item in resources
        }
    )
    evidence = {
        "source": "NEO4J_AND_POSTGRESQL",
        "tool": "find_single_point_failure_candidates",
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
        "current_resource_states": resources,
        "missing_states": [_typed(node) for node in evaluation.missing_states],
        "state_temporal_scope": "CURRENT_STATE_AT_OBSERVATION",
    }
    budget.require()
    result = ReadResult(json_value(data), json_value(evidence))
    budget.require()
    return result
