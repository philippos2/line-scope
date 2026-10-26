from dataclasses import replace

import pytest
from graph.test_alternative_facts import AS_OF, OP, OTHER, M, P, Q
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from sqlalchemy import column, delete, table, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

from application.test_alternative_analysis import CountingStates
from linescope.application.reads import ToolError
from linescope.application.spof_analysis import evaluate_spof_facts
from linescope.demo_graph_seed import demo_id
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.spof_facts import collect_spof_facts


def evaluate(reader, db, candidates=(M, OP), *, historical=False, max_nodes=9, states=None):
    budget = GraphAnalysisBudget(5000)
    states = states or CountingStates(db)
    with reader.open(budget) as read:
        facts = collect_spof_facts(
            read, (P, Q), candidates, as_of=AS_OF, max_depth=16, max_nodes=max_nodes, page_size=1
        )
        result = evaluate_spof_facts(facts, states, budget, historical=historical)
    assert len(states.calls) == 1
    return result


def test_candidates_are_excluded_individually_with_one_observation(reader_world, db):
    states = CountingStates(db)
    result = evaluate(reader_world[0], db, states=states)
    assert result.complete and len(result.findings) == 4
    outcomes = {(item.target, item.candidate): item.determination for item in result.findings}
    assert outcomes == {(P, M): "NOT_SPOF", (Q, M): "NOT_SPOF", (P, OP): "SPOF", (Q, OP): "SPOF"}
    assert all(item.excluded_nodes == frozenset({item.target}) for item in result.replacements)
    assert states.calls[0][0] == [M[1], OTHER[1]]
    assert len(states.calls[0][1]) == 2


@pytest.mark.parametrize("historical", [False, True])
def test_missing_or_historical_replacement_is_indeterminate(reader_world, db, historical):
    if not historical:
        state = table("equipment_current_state", column("equipment_id", PGUUID()))
        statement = delete(state).where(state.c.equipment_id == OTHER[1]).compile(dialect=dialect())
        with db.transaction() as connection:
            connection.execute(str(statement), statement.params)
    result = evaluate(reader_world[0], db, (M,), historical=historical)
    assert result.complete and all(
        item.determination == "INDETERMINATE" for item in result.findings
    )
    assert result.historical is historical
    if not historical:
        assert result.missing_states == tuple(
            sorted((OTHER, ("InfrastructureResource", str(demo_id("R-02")))))
        )


def test_unrelated_candidate_is_not_spof(reader_world, db):
    result = evaluate(reader_world[0], db, (OTHER,))
    assert all(
        item.determination == "NOT_SPOF" and item.reason == "NOT_MANDATORY_UPSTREAM"
        for item in result.findings
    )


def test_known_stopped_replacement_establishes_spof_candidate(reader_world, db):
    state = table("equipment_current_state", column("equipment_id", PGUUID()), column("state_code"))
    statement = (
        update(state)
        .where(state.c.equipment_id == OTHER[1])
        .values(state_code="STOPPED")
        .compile(dialect=dialect())
    )
    with db.transaction() as connection:
        connection.execute(str(statement), statement.params)
    result = evaluate(reader_world[0], db, (M,))
    assert result.complete and all(item.determination == "SPOF" for item in result.findings)
    assert result.replacements[0].availability == "UNAVAILABLE"


def test_truncation_never_proves_no_replacement(reader_world, db):
    result = evaluate(reader_world[0], db, max_nodes=8)
    assert not result.complete and result.limit_reason == "NODE_COUNT"
    assert all(item.determination == "INDETERMINATE" for item in result.findings)


def test_explicit_empty_keeps_no_findings_without_fake_evaluations(reader_world, db):
    result = evaluate(reader_world[0], db, ())
    assert result.complete and result.findings == result.replacements == ()
    assert len(result.observation["operations"]) == 2


def test_mismatched_facts_fail_before_state_read(reader_world):
    budget = GraphAnalysisBudget(5000)
    with reader_world[0].open(budget) as read:
        facts = collect_spof_facts(
            read, (P,), (M,), as_of=AS_OF, max_depth=16, max_nodes=9, page_size=1
        )

        class NoStates:
            def read_availability(self, *args, **kwargs):
                pytest.fail("Mismatched facts must fail before state I/O")

        with pytest.raises(ValueError):
            evaluate_spof_facts(
                replace(facts, substitutes=()), NoStates(), budget, historical=False
            )


def test_final_gate_prevents_publishing_result_after_rebuild_starts(reader_world, db):
    class RebuildingStates(CountingStates):
        def read_availability(self, equipment_ids, operation_ids, budget, **kwargs):
            result = super().read_availability(equipment_ids, operation_ids, budget, **kwargs)
            control = table("graph_projection_control", column("rebuild_flag"))
            statement = update(control).values(rebuild_flag=True).compile(dialect=dialect())
            with db.transaction() as connection:
                connection.execute(str(statement), statement.params)
            return result

    with pytest.raises(ToolError) as caught:
        evaluate(reader_world[0], db, states=RebuildingStates(db))
    assert caught.value.code == "GRAPH_REBUILDING"


def test_spof_includes_registered_common_supply_and_evidence(db, adapters):
    from uuid import uuid4

    from interfaces.test_alternative_api import supply_world

    from linescope.application.graph_analysis import GraphAnalysis
    from linescope.application.graph_request import GraphLimits
    from linescope.execution import ExecutionContext
    from linescope.graph.analysis_reader import GraphAnalysisReader
    from linescope.graph.analysis_states import GraphStateReader

    args = supply_world(db, adapters, "UNAVAILABLE")
    result = GraphAnalysis(
        GraphAnalysisReader(db, adapters[1].driver),
        GraphStateReader(db),
        system_limits=GraphLimits(16, 100, 100, 5000),
        budget_factory=GraphAnalysisBudget,
    ).call(
        ExecutionContext("reader", "manager", uuid4()),
        "find_single_point_failure_candidates",
        {"important_targets": args["important_targets"], "candidate_nodes": args["excluded_nodes"]},
    )
    assert result.evidence["current_resource_states"][0]["supply_state"] == "UNAVAILABLE"
    assert result.evidence["current_resource_states"][0]["record_reference"]["version"] == 1
    assert result.data["findings"][0]["alternatives"]["availability"] == "UNAVAILABLE"
