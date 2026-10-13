"""Shared bounded fulfillment paths; no business classification or storage."""

from ..domain.graph_paths import representative_paths
from .graph_evidence import serialize_paths
from .reads import ToolError


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


def collect_fulfillment_paths(facts, budget, max_paths):
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
        raise ToolError(
            "GRAPH_UNAVAILABLE", "Graph fulfillment path facts are inconsistent"
        ) from error
    return paths, mandatory, substitutions, omitted
