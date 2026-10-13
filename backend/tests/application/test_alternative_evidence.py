from dataclasses import replace
from datetime import datetime, timezone

import pytest
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world

from linescope.application.alternative_analysis import evaluate_alternative_facts
from linescope.application.alternative_evidence import build_alternative_result
from linescope.application.reads import ToolError
from linescope.demo_graph_seed import demo_id
from linescope.graph.alternative_facts import collect_alternative_facts
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_states import GraphStateReader

AS_OF = datetime(2026, 10, 13, tzinfo=timezone.utc)
P = ("Product", str(demo_id("P-100")))
Q = ("Product", str(demo_id("P-200")))
M = ("Equipment", "20400000-0000-4000-8000-000000000001")
OTHER = ("Equipment", "20800000-0000-4000-8000-000000000001")


def build(reader, db, *, max_paths=100, max_nodes=9, historical=False, damage=None):
    budget = GraphAnalysisBudget(5000)
    with reader.open(budget) as read:
        facts = collect_alternative_facts(
            read, (P, Q), (M,), as_of=AS_OF, max_depth=16, max_nodes=max_nodes, page_size=1
        )
        evaluation = evaluate_alternative_facts(
            facts, GraphStateReader(db), budget, historical=historical
        )
        if damage == "mandatory":
            facts = replace(facts, dependency_edges=())
        elif damage == "mode":
            evaluation = replace(evaluation, historical=not historical)
        elif damage == "exclusions":
            evaluation = replace(
                evaluation,
                replacements=(replace(evaluation.replacements[0], excluded_nodes=frozenset()),),
            )
        elif damage == "substitution":
            facts = replace(
                facts, substitutes=(replace(facts.substitutes[0], substitution_edges=()),)
            )
        result = build_alternative_result(
            facts,
            evaluation,
            budget,
            max_paths=max_paths,
            graph_generation=read.validation.generation,
            graph_observed_at=read.observed_at,
            as_of=AS_OF,
            historical=historical,
        )
    return result


def test_complete_paths_and_direct_substitution_preserve_records_and_direction(reader_world, db):
    result = build(reader_world[0], db)
    assert result.data["complete"] and result.data["determination"] == "DETERMINATE"
    assert len(result.data["representative_paths"]) == 14
    assert result.data["representative_paths"] == result.evidence["representative_paths"]
    substitution = next(
        path for path in result.data["representative_paths"] if path["purpose"] == "SUBSTITUTION"
    )
    assert [node["entity_id"] for node in substitution["nodes"]] == [M[1], OTHER[1]]
    edge = substitution["edges"][0]
    assert edge["source"]["entity_id"] == OTHER[1] and edge["target"]["entity_id"] == M[1]
    assert edge["traversal_source"]["entity_id"] == M[1] and edge["source_version"] == 1
    assert result.evidence["graph_generation"] == reader_world[1]
    assert len(result.evidence["mandatory_relations"]) == 9
    assert len(result.evidence["state_versions"]) == 4
    assert result.data["analysis_scope"] == "DEPENDENCY_FULFILLMENT"
    assert "SAFETY" in result.data["not_evaluated"]


@pytest.mark.parametrize("max_paths", [1, 13])
def test_path_budget_never_publishes_definitive_result_with_missing_proofs(
    reader_world, db, max_paths
):
    result = build(reader_world[0], db, max_paths=max_paths)
    assert len(result.data["representative_paths"]) == max_paths
    assert not result.data["complete"] and result.data["limit_reason"] == "PATH_COUNT"
    assert result.data["determination"] == "INDETERMINATE"
    assert all(
        item["after"]["determination"] == "INDETERMINATE" for item in result.data["target_results"]
    )
    assert result.data["alternatives"][0]["availability"] == "UNKNOWN"
    assert result.evidence["current_states"]


def test_exact_path_limit_does_not_mean_truncation(reader_world, db):
    assert build(reader_world[0], db, max_paths=14).data["complete"]


def test_node_limit_precedes_path_limit(reader_world, db):
    result = build(reader_world[0], db, max_nodes=8, max_paths=1)
    assert result.data["limit_reason"] == "NODE_COUNT"
    assert result.data["determination"] == "INDETERMINATE"


def test_historical_scope_retains_current_observation_without_past_claim(reader_world, db):
    result = build(reader_world[0], db, historical=True)
    assert result.data["complete"] and result.data["determination"] == "INDETERMINATE"
    assert result.evidence["state_temporal_scope"] == "CURRENT_STATE_AT_OBSERVATION"
    assert result.evidence["analysis_mode"] == "EXPLICIT_HISTORICAL"


@pytest.mark.parametrize("damage", ["mandatory", "substitution"])
def test_no_unreturned_relation_can_be_invented_as_evidence(reader_world, db, damage):
    with pytest.raises(ToolError) as caught:
        build(reader_world[0], db, damage=damage)
    assert caught.value.code == "GRAPH_UNAVAILABLE"


@pytest.mark.parametrize("max_paths", [0, True, "1"])
def test_invalid_server_path_limits_fail(reader_world, db, max_paths):
    with pytest.raises(ValueError):
        build(reader_world[0], db, max_paths=max_paths)


@pytest.mark.parametrize("damage", ["mode", "exclusions"])
def test_evidence_must_match_evaluated_mode_and_exclusion_set(reader_world, db, damage):
    with pytest.raises(ValueError):
        build(reader_world[0], db, damage=damage)
