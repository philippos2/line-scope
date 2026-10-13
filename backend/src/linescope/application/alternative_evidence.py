"""Server-built alternative DTO/Evidence from verified facts and evaluations.

No storage, HTTP or LLM. Caller owns authorization and successful Graph exit.
"""

from datetime import datetime

from ..domain.canonical import normalize_uuid
from ..domain.graph_paths import representative_paths
from ..domain.graph_traversal import IMPACT_FORWARD, IMPACT_REVERSE
from .graph_analysis import UNEVALUATED_DIMENSIONS, serialize_paths
from .reads import ReadResult, ToolError, json_value


def _typed(node):
    return {"entity_type": node[0], "entity_id": node[1]}


def _relation(edge):
    return {
        "source_record_id": edge["source_record_id"],
        "source_version": edge["source_version"],
        "relation_type": edge["relation_type"],
        "required": edge["required"],
        "source": _typed((edge["source_type"], edge["source_id"])),
        "target": _typed((edge["target_type"], edge["target_id"])),
    }


def _reason(reason):
    reasons = {
        "MANDATORY_CYCLE": "CYCLIC_REQUIREMENTS",
        "UNKNOWN_REPLACEMENT": "UNKNOWN_AVAILABILITY",
        "INCOMPLETE": "INCOMPLETE_SEARCH",
    }
    return reasons.get(reason, reason)


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
    records = {edge["source_record_id"]: edge for edge in facts.dependency_edges}
    paths, seen_roots, omitted = [], set(), False
    searches = list(facts.target_searches)
    for substitute in facts.substitutes:
        searches.extend(substitute.searches)
    try:
        for root, reached in searches:
            budget.require()
            if root in seen_roots:
                continue
            seen_roots.add(root)
            if [item.node for item in reached.nodes if item.distance == 0] != [root]:
                raise ValueError("Path root mismatch")
            selected = representative_paths(reached, max_paths=max_paths + 1)
            for path in selected.paths:
                budget.require()
                if len(paths) == max_paths:
                    omitted = True
                    break
                encoded = serialize_paths((path,), records, "UPSTREAM")[0]
                paths.append({"purpose": "MANDATORY_DEPENDENCY", "root": _typed(root), **encoded})
            if omitted:
                break
        substitutions = []
        for captured in facts.substitutes:
            for edge in captured.substitution_edges:
                budget.require()
                source = (edge["source_type"], edge["source_id"])
                target = (edge["target_type"], edge["target_id"])
                if (
                    edge["relation_type"] != "CAN_SUBSTITUTE"
                    or target != captured.target
                    or source not in captured.candidates
                ):
                    raise ValueError("Substitution relation mismatch")
                relation = _relation(edge)
                substitutions.append(relation)
                if len(paths) == max_paths:
                    omitted = True
                    continue
                paths.append(
                    {
                        "purpose": "SUBSTITUTION",
                        "root": _typed(target),
                        "nodes": [_typed(target), _typed(source)],
                        "hops": 1,
                        "edges": [
                            {
                                **relation,
                                "traversal_direction": "SUBSTITUTION",
                                "traversal_source": _typed(target),
                                "traversal_target": _typed(source),
                            }
                        ],
                    }
                )
        for captured in facts.substitutes:
            proven = {
                (
                    item["target"]["entity_type"],
                    item["target"]["entity_id"],
                    item["source"]["entity_type"],
                    item["source"]["entity_id"],
                )
                for item in substitutions
            }
            if any(
                (*captured.target, *candidate) not in proven for candidate in captured.candidates
            ):
                raise ValueError("Candidate has no direct relation evidence")
        mandatory = []
        for edge in facts.dependency_edges:
            budget.require()
            mandatory.append(_relation(edge))
    except (KeyError, TypeError, ValueError) as error:
        raise ToolError("GRAPH_UNAVAILABLE", "Alternative path facts are inconsistent") from error
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
