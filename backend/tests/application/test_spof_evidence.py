from dataclasses import replace

import pytest
from graph.test_alternative_facts import AS_OF, OP, OTHER, M, P, Q
from graph.test_common_dependency_reader import graph_driver as graph_driver

from application.graph_evidence_fixtures import db as db
from application.graph_evidence_fixtures import evidence_world as evidence_world
from application.graph_evidence_fixtures import reader_world as reader_world
from linescope.application.reads import ToolError
from linescope.application.spof_analysis import evaluate_spof_facts
from linescope.application.spof_evidence import build_spof_result
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_states import GraphStateReader
from linescope.graph.spof_facts import collect_spof_facts


def build(reader, db, *, max_paths=100, max_nodes=9, historical=False, damage=None):
    budget = GraphAnalysisBudget(5000)
    with reader.open(budget) as read:
        facts = collect_spof_facts(
            read, (P, Q), (M, OP), as_of=AS_OF, max_depth=16, max_nodes=max_nodes, page_size=1
        )
        evaluation = evaluate_spof_facts(facts, GraphStateReader(db), budget, historical=historical)
        if damage == "mode":
            evaluation = replace(evaluation, historical=not historical)
        elif damage == "targets":
            facts = replace(facts, important_targets=(Q,))
        elif damage == "exclusions":
            evaluation = replace(
                evaluation,
                replacements=tuple(
                    replace(item, excluded_nodes=frozenset({M, OP}))
                    for item in evaluation.replacements
                ),
            )
        elif damage == "mandatory":
            facts = replace(facts, dependency_edges=())
        elif damage == "substitution":
            facts = replace(
                facts,
                substitutes=tuple(
                    replace(item, substitution_edges=()) for item in facts.substitutes
                ),
            )
        result = build_spof_result(
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


def test_public_classification_and_state_relation_evidence(reader_world, db):
    result = build(reader_world[0], db)
    assert result.data["complete"] and result.data["determination"] == "DETERMINATE"
    outcomes = {
        item["candidate"]["entity_id"]: item["determination"] for item in result.data["findings"]
    }
    assert outcomes == {M[1]: "NOT_CANDIDATE", OP[1]: "CANDIDATE"}
    assert result.data["representative_paths"] == result.evidence["representative_paths"]
    assert result.evidence["graph_generation"] == reader_world[1]
    assert len(result.evidence["state_versions"]) == 4
    edge = next(
        path for path in result.data["representative_paths"] if path["purpose"] == "SUBSTITUTION"
    )["edges"][0]
    assert edge["source"]["entity_id"] == OTHER[1] and edge["traversal_source"]["entity_id"] == M[1]
    assert "SAFETY" in result.data["not_evaluated"]


def test_exact_path_budget_is_complete_but_one_less_is_not(reader_world, db):
    count = len(build(reader_world[0], db).data["representative_paths"])
    assert build(reader_world[0], db, max_paths=count).data["complete"]
    result = build(reader_world[0], db, max_paths=count - 1)
    assert not result.data["complete"] and result.data["limit_reason"] == "PATH_COUNT"
    assert all(item["determination"] == "INDETERMINATE" for item in result.data["findings"])


def test_node_budget_has_priority_over_path_count(reader_world, db):
    result = build(reader_world[0], db, max_nodes=8, max_paths=1)
    assert result.data["limit_reason"] == "NODE_COUNT"
    assert result.data["determination"] == "INDETERMINATE"


def test_historical_availability_is_not_claimed_from_current_observation(reader_world, db):
    result = build(reader_world[0], db, historical=True)
    assert result.data["complete"] and result.data["determination"] == "INDETERMINATE"
    assert result.evidence["state_temporal_scope"] == "CURRENT_STATE_AT_OBSERVATION"


@pytest.mark.parametrize("damage", ["mode", "exclusions", "targets"])
def test_reused_evaluation_with_different_exclusions_or_mode_rejected(reader_world, db, damage):
    with pytest.raises(ValueError):
        build(reader_world[0], db, damage=damage)


@pytest.mark.parametrize("damage", ["mandatory", "substitution"])
def test_missing_relation_evidence_cannot_be_invented(reader_world, db, damage):
    with pytest.raises(ToolError) as caught:
        build(reader_world[0], db, damage=damage)
    assert caught.value.code == "GRAPH_UNAVAILABLE"
