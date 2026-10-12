from datetime import datetime, timezone

import pytest
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from sqlalchemy import column, delete, table, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

from linescope.application.reads import ToolError
from linescope.application.substitute_analysis import evaluate_substitute_facts
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_states import GraphStateReader
from linescope.graph.substitute_facts import collect_substitute_facts

AS_OF = datetime(2026, 10, 13, tzinfo=timezone.utc)
M = ("Equipment", "20400000-0000-4000-8000-000000000001")
OTHER = ("Equipment", "20800000-0000-4000-8000-000000000001")


def evaluate(reader, db, *, historical=False, states=None, excluded=()):
    budget = GraphAnalysisBudget(5000)
    with reader.open(budget) as read:
        facts = collect_substitute_facts(
            read, M, as_of=AS_OF, max_depth=16, max_nodes=3, page_size=1
        )
        result = evaluate_substitute_facts(
            facts, states or GraphStateReader(db), budget, historical=historical, excluded=excluded
        )
    return result


def execute(db, stmt):
    compiled = stmt.compile(dialect=dialect())
    with db.transaction() as connection:
        connection.execute(str(compiled), compiled.params)


def test_real_graph_and_postgres_states_produce_available_direct_substitute(reader_world, db):
    result = evaluate(reader_world[0], db)
    assert result.selection.availability == "AVAILABLE"
    assert result.missing_states == ()
    assert result.observation["observed_at"].tzinfo is not None
    assert {item["state_code"] for item in result.observation["states"]} == {"RUNNING", "STOPPED"}


def test_stopped_candidate_is_unavailable_from_authoritative_state(reader_world, db):
    state = table("equipment_current_state", column("equipment_id", PGUUID()), column("state_code"))
    execute(db, update(state).where(state.c.equipment_id == OTHER[1]).values(state_code="STOPPED"))
    assert evaluate(reader_world[0], db).selection.availability == "UNAVAILABLE"


def test_missing_state_is_unknown_and_identified(reader_world, db):
    state = table("equipment_current_state", column("equipment_id", PGUUID()))
    execute(db, delete(state).where(state.c.equipment_id == OTHER[1]))
    result = evaluate(reader_world[0], db)
    assert result.selection.availability == "UNKNOWN"
    assert result.missing_states == (OTHER,)


def test_historical_does_not_infer_past_from_current_running_state(reader_world, db):
    result = evaluate(reader_world[0], db, historical=True)
    assert result.selection.availability == "UNKNOWN"
    assert result.observation["states"]  # Current facts remain explicit evidence, not past state.


def test_combined_empty_state_read_retains_statement_time(reader_world, db):
    result = GraphStateReader(db).read_availability([], [], GraphAnalysisBudget(5000))
    assert result["states"] is None and result["operations"] is None
    assert result["observed_at"].tzinfo is not None


@pytest.mark.parametrize("damage", ["version", "status", "timestamp", "duplicate", "unrequested"])
def test_invalid_state_adapter_facts_fail_closed(reader_world, db, damage):
    delegate = GraphStateReader(db)

    class DamagedStates:
        def read_availability(self, equipment_ids, operation_ids, budget):
            observation = delegate.read_availability(equipment_ids, operation_ids, budget)
            if damage == "version":
                observation["states"][0]["version"] = True
            elif damage == "status":
                observation["states"][0]["state_code"] = "SAFE"
            elif damage == "timestamp":
                observation["observed_at"] = datetime(2026, 10, 13)
            elif damage == "duplicate":
                observation["states"].append(dict(observation["states"][0]))
            else:
                observation["states"][0]["equipment_id"] = "00000000-0000-4000-8000-000000000001"
            return observation

    with pytest.raises(ToolError) as caught:
        evaluate(reader_world[0], db, states=DamagedStates())
    assert caught.value.code == "INTERNAL_ERROR"
    assert "SAFE" not in caught.value.message


def test_operation_planned_status_and_version_are_observed_with_equipment(reader_world, db):
    from linescope.demo_graph_seed import demo_id

    identifier = str(demo_id("OP-30"))
    result = GraphStateReader(db).read_availability(
        [OTHER[1]], [identifier], GraphAnalysisBudget(5000)
    )
    assert result["operations"] == [
        {"production_operation_id": identifier, "planned_status": "PLANNED", "version": 1}
    ]
    assert result["states"][0]["equipment_id"] == OTHER[1]
    assert result["observed_at"].tzinfo is not None
    operation = table(
        "production_operation",
        column("production_operation_id", PGUUID()),
        column("planned_status"),
    )
    execute(
        db,
        update(operation)
        .where(operation.c.production_operation_id == identifier)
        .values(planned_status="CANCELLED"),
    )
    changed = GraphStateReader(db).read_availability([], [identifier], GraphAnalysisBudget(5000))
    assert changed["operations"][0]["planned_status"] == "CANCELLED"


def test_inactive_operation_is_not_a_state_availability_fact(reader_world, db):
    from linescope.demo_graph_seed import demo_id

    identifier = str(demo_id("OP-30"))
    operation = table(
        "production_operation", column("production_operation_id", PGUUID()), column("active")
    )
    execute(
        db,
        update(operation)
        .where(operation.c.production_operation_id == identifier)
        .values(active=False),
    )
    result = GraphStateReader(db).read_availability([], [identifier], GraphAnalysisBudget(5000))
    assert result["operations"] is None


def test_excluded_candidate_is_unavailable_even_when_postgres_says_running(reader_world, db):
    result = evaluate(reader_world[0], db, excluded=(OTHER,))
    assert result.selection.availability == "UNAVAILABLE"
    assert result.selection.excluded_nodes == frozenset({M, OTHER})
    assert any(
        row["equipment_id"] == OTHER[1] and row["state_code"] == "RUNNING"
        for row in result.observation["states"]
    )


@pytest.mark.parametrize(
    "excluded", [None, "x", (False,), (("SQL", OTHER[1]),), (("Equipment", "invalid"),)]
)
def test_bad_exclusions_fail_before_state_read(reader_world, db, excluded):
    class NoStateRead:
        def read_availability(self, *args):
            pytest.fail("Invalid exclusions must be rejected before state I/O")

    with pytest.raises(ValueError):
        evaluate(reader_world[0], db, states=NoStateRead(), excluded=excluded)
