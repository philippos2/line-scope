from dataclasses import replace
from datetime import datetime, timezone

import pytest
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from sqlalchemy import column, delete, table, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

from linescope.application.alternative_analysis import evaluate_alternative_facts
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
OP = ("ProductionOperation", str(demo_id("OP-30")))


class CountingStates:
    def __init__(self, db):
        self.delegate = GraphStateReader(db)
        self.calls = []

    def read_availability(self, equipment_ids, operation_ids, budget):
        self.calls.append((equipment_ids, operation_ids))
        return self.delegate.read_availability(equipment_ids, operation_ids, budget)


def evaluate(
    reader, db, *, targets=(P, Q), excluded=(M,), max_nodes=9, historical=False, states=None
):
    budget = GraphAnalysisBudget(5000)
    states = states or CountingStates(db)
    with reader.open(budget) as read:
        facts = collect_alternative_facts(
            read,
            targets,
            excluded,
            as_of=AS_OF,
            max_depth=16,
            max_nodes=max_nodes,
            page_size=1,
        )
        result = evaluate_alternative_facts(facts, states, budget, historical=historical)
    assert len(states.calls) == 1
    return result, states.calls[0]


def test_multiple_targets_use_one_observation_and_available_direct_replacement(reader_world, db):
    result, requested = evaluate(reader_world[0], db)
    assert result.complete and {item.target for item in result.targets} == {P, Q}
    assert all(
        item.before.determination == item.after.determination == "ESTABLISHED"
        for item in result.targets
    )
    assert result.replacements[0].availability == "AVAILABLE"
    assert requested[0] == [M[1], OTHER[1]]
    assert len(requested[1]) == 2 and len(result.observation["operations"]) == 2
    assert result.missing_states == ()


def test_excluding_running_alternative_prevents_restoration(reader_world, db):
    result, _ = evaluate(reader_world[0], db, excluded=(M, OTHER))
    assert all(item.after.determination == "NOT_ESTABLISHED" for item in result.targets)
    assert all(item.excluded_nodes == frozenset({M, OTHER}) for item in result.replacements)


def test_operation_exclusion_is_not_waived_by_equipment_replacement(reader_world, db):
    result, _ = evaluate(reader_world[0], db, excluded=(M, OP))
    assert all(item.after.determination == "NOT_ESTABLISHED" for item in result.targets)
    operation = next(item for item in result.replacements if item.target == OP)
    assert operation.availability == "UNAVAILABLE" and operation.candidates == ()


def test_target_results_remain_individual(reader_world, db):
    result, _ = evaluate(reader_world[0], db, targets=(P, OTHER), excluded=(OTHER,))
    outcomes = {item.target: item.after.determination for item in result.targets}
    assert outcomes == {P: "ESTABLISHED", OTHER: "NOT_ESTABLISHED"}


def test_missing_state_is_partial_knowledge_not_no_alternative(reader_world, db):
    state = table("equipment_current_state", column("equipment_id", PGUUID()))
    stmt = delete(state).where(state.c.equipment_id == OTHER[1]).compile(dialect=dialect())
    with db.transaction() as connection:
        connection.execute(str(stmt), stmt.params)
    result, _ = evaluate(reader_world[0], db)
    assert result.complete  # Graph complete, decision unknown.
    assert result.missing_states == (OTHER,)
    assert all(item.after.determination == "INDETERMINATE" for item in result.targets)


def test_past_analysis_does_not_reuse_current_running_candidate(reader_world, db):
    result, _ = evaluate(reader_world[0], db, historical=True)
    assert result.complete and result.observation["states"]
    assert all(item.after.determination == "INDETERMINATE" for item in result.targets)


def test_node_truncation_does_not_claim_unavailable_alternative(reader_world, db):
    result, _ = evaluate(reader_world[0], db, max_nodes=8)
    assert not result.complete and result.limit_reason == "NODE_COUNT"
    assert all(item.after.determination == "INDETERMINATE" for item in result.targets)


def test_inconsistent_whole_analysis_facts_rejected_before_state_io(reader_world):
    reader, _ = reader_world
    budget = GraphAnalysisBudget(5000)
    with reader.open(budget) as read:
        facts = collect_alternative_facts(
            read, (P,), (M,), as_of=AS_OF, max_depth=16, max_nodes=9, page_size=1
        )
        bad = replace(facts, substitutes=())

        class NoRead:
            def read_availability(self, *args):
                pytest.fail("Mismatched facts must not trigger state I/O")

        with pytest.raises(ValueError):
            evaluate_alternative_facts(bad, NoRead(), budget, historical=False)


def test_end_gate_rejects_evaluated_result_when_rebuild_begins(reader_world, db):
    class RebuildingStates(CountingStates):
        def read_availability(self, equipment_ids, operation_ids, budget):
            result = super().read_availability(equipment_ids, operation_ids, budget)
            control = table("graph_projection_control", column("rebuild_flag"))
            statement = update(control).values(rebuild_flag=True).compile(dialect=dialect())
            with db.transaction() as connection:
                connection.execute(str(statement), statement.params)
            return result

    with pytest.raises(ToolError) as caught:
        evaluate(reader_world[0], db, states=RebuildingStates(db))
    assert caught.value.code == "GRAPH_REBUILDING"
