"""Real PG shared lock and start/end state gates; no Neo4j proof is inferred."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest

from graph.test_projection_queue import queued as queued
from graph.test_rebuild_control import row
from graph.test_rebuild_control import store as store
from graph.test_rebuild_drain import Clock
from linescope.application.reads import ToolError
from linescope.graph.analysis_gate import GraphAnalysisGate
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.rebuild_drain import DeadlineLeadership
from linescope.persistence.database import Database


def budget(seconds=2):
    clock = Clock()
    return DeadlineLeadership(SimpleNamespace(require=lambda: None), clock.now + seconds, clock)


def current(store):
    generation = uuid4()
    with store.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL,rebuild_flag=false",
            (generation,),
        )
    return generation


def test_shared_analysis_blocks_mutation_and_releases_on_exit(store):
    generation = current(store)
    contender = Database(replace(store.settings, lock_ms=50, statement_ms=1000))
    with GraphAnalysisGate(store).open(budget()) as observed:
        assert observed.status == "CURRENT" and observed.active_generation == generation
        with contender.transaction() as c:
            acquire_graph_mutation_lock(c, shared=True)
        with pytest.raises(psycopg.errors.LockNotAvailable), contender.transaction() as c:
            acquire_graph_mutation_lock(c, shared=False)
    with contender.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)


@pytest.mark.parametrize(
    ("flag", "fatal", "code"),
    [(True, None, "GRAPH_REBUILDING"), (False, "FAILURE", "GRAPH_UNAVAILABLE")],
)
@pytest.mark.parametrize("at_end", [False, True])
def test_noncurrent_start_or_end_rejects_results(store, flag, fatal, code, at_end):
    current(store)

    def change():
        with store.transaction() as c:
            c.execute(
                "UPDATE graph_projection_control SET rebuild_flag=%s,fatal_error=%s", (flag, fatal)
            )

    if not at_end:
        change()
    entered = False
    with pytest.raises(ToolError) as caught:
        with GraphAnalysisGate(store).open(budget()):
            entered = True
            change()
    assert caught.value.code == code
    assert entered == at_end


def test_generation_change_rejects_otherwise_current_result(store):
    current(store)
    with pytest.raises(ToolError) as caught:
        with GraphAnalysisGate(store).open(budget()):
            current(store)
    assert caught.value.code == "GRAPH_NOT_CURRENT"


def test_missing_generation_refuses_entry(store):
    with pytest.raises(ToolError) as caught, GraphAnalysisGate(store).open(budget()):
        pytest.fail("Missing projection must not permit analysis")
    assert caught.value.code == "GRAPH_UNAVAILABLE"


def test_shared_lock_wait_uses_budget_without_changing_control(store):
    current(store)
    before = row(store)
    with store.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=False)
        with pytest.raises(ToolError) as caught, GraphAnalysisGate(store).open(budget(0.1)):
            pytest.fail("Exclusive mutation lock must block analysis")
    assert caught.value.code == "RESOURCE_BUSY"
    assert row(store) == before


def test_evidence_failure_releases_shared_lock(store):
    current(store)
    with pytest.raises(ValueError, match="evidence"):
        with GraphAnalysisGate(store).open(budget()):
            raise ValueError("evidence")
    with store.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)


def test_expired_analysis_budget_discards_result(store):
    current(store)
    guard = budget()
    with pytest.raises(ToolError) as caught:
        with GraphAnalysisGate(store).open(guard):
            guard.clock.now += 3
    assert caught.value.code == "RESOURCE_BUSY"


def test_gate_transaction_is_read_only(store, monkeypatch):
    current(store)
    before = row(store)
    gate = GraphAnalysisGate(store)

    def mutation(connection):
        connection.execute("UPDATE graph_projection_control SET fatal_error='unexpected'")

    monkeypatch.setattr(gate.state, "observe", mutation)
    with pytest.raises(ToolError) as caught, gate.open(budget()):
        pytest.fail("Read-only gate must reject mutation")
    assert caught.value.code == "INTERNAL_ERROR"
    assert isinstance(caught.value.__cause__, psycopg.errors.ReadOnlySqlTransaction)
    assert row(store) == before


@pytest.mark.parametrize("at_end", [False, True])
def test_lagging_start_or_end_refuses_payload(queued, at_end):
    db, _, _ = queued
    current(db)
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET status='APPLIED',processed_at=statement_timestamp()")

    def lagging():
        with db.transaction() as c:
            c.execute("UPDATE graph_outbox SET status='PENDING',processed_at=NULL")

    if not at_end:
        lagging()
    entered = False
    with pytest.raises(ToolError) as caught:
        with GraphAnalysisGate(db).open(budget()):
            entered = True
            lagging()
    assert caught.value.code == "GRAPH_NOT_CURRENT"
    assert entered == at_end
