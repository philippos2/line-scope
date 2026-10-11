"""Real PG/Neo4j one-step orchestration and named failure boundaries."""

import io
import json
from uuid import UUID

import psycopg
import pytest
from neo4j.exceptions import ClientError, ConfigurationError, ServiceUnavailable, TransientError

from graph.test_neo4j_projection import facts, seed_endpoints
from graph.test_neo4j_projection import graph as graph
from graph.test_neo4j_projection import graph_driver as graph_driver
from graph.test_outbox import events
from graph.test_projection_queue import queued as queued
from graph.test_projection_worker import SECRET, FailingAdapter
from graph.test_rebuild_application import RecordingAdapter
from graph.test_rebuild_queue import prepare
from graph.test_rebuild_queue import world as world
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.neo4j_projection import GraphGenerationUnavailable, ProjectionIntegrityError
from linescope.graph.rebuild_step import RebuildStep
from linescope.logging import EventLogger, current_request_id, request_context


def step(db, adapter):
    output = io.StringIO()
    return RebuildStep(db, adapter, logger=EventLogger(stream=output)), output


def logs(output):
    assert SECRET not in output.getvalue()
    return [json.loads(line) for line in output.getvalue().splitlines()]


def stored(db, identifier):
    return next(row for row in events(db) if row["outbox_id"] == identifier)


def test_real_graph_drain_three_events_then_drained_without_releasing_lock(world, graph):
    _, generation, adapter = graph
    with world.transaction() as c:
        c.execute("UPDATE graph_projection_control SET active_generation=%s", (UUID(generation),))
    for event in events(world):
        seed_endpoints(graph, event["payload"])
    service, output = step(world, adapter)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        for _ in range(3):
            assert service.run_once(leader, lock, ticket).status == "APPLIED"
        assert service.run_once(leader, lock, ticket).status == "DRAINED"
        leader.require()
        with world.transaction() as c:
            control = c.execute("SELECT * FROM graph_projection_control").fetchone()
        assert control["rebuild_flag"] is True and control["active_generation"] == UUID(generation)
        assert control["fatal_error"] is not None  # Only validated publish clears it.
    recorded = logs(output)
    assert len(recorded) == 3 and len(facts(graph)[0]) == 3
    assert all(
        row["event"] == "projection.attempt.completed" and row["after_status"] == "APPLIED"
        for row in recorded
    )
    assert all(
        row["rebuild_id"] == str(ticket.rebuild_id) and row["graph_generation"] == generation
        for row in recorded
    )
    assert len({row["request_id"] for row in recorded}) == 3
    assert current_request_id() is None


@pytest.mark.parametrize("status", ["PROCESSING", "RETRYABLE", "DEAD", "APPLIED"])
def test_no_candidate_never_calls_adapter_or_logs_fake_attempt(world, status):
    with world.transaction() as c:
        c.execute(
            "UPDATE graph_outbox SET status=%s,attempt_count=2,processing_started_at=statement_timestamp(),next_attempt_at=statement_timestamp()+interval '1 hour'",
            (status,),
        )
    service, output = step(world, FailingAdapter(RuntimeError(SECRET)))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        before = events(world)
        result = service.run_once(leader, lock, ticket)
    assert result.status == (
        "DEAD" if status == "DEAD" else "DRAINED" if status == "APPLIED" else "WAITING"
    )
    assert service.adapter.calls == 0 and events(world) == before and not logs(output)


@pytest.mark.parametrize(
    "error",
    [
        ServiceUnavailable(SECRET),
        TransientError(SECRET),
        psycopg.OperationalError(SECRET),
        psycopg.errors.QueryCanceled(SECRET),
        GraphGenerationUnavailable(SECRET),
    ],
)
def test_known_transient_saved_once_with_correlated_logs(world, error):
    service, output = step(world, FailingAdapter(error))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        result = service.run_once(leader, lock, ticket)
    assert result.status == "RETRYABLE" and service.adapter.calls == 1
    row = stored(world, result.outbox_id)
    assert row["attempt_count"] == 1 and row["last_error"] == "PROJECTION_TRANSIENT_FAILURE"
    recorded = logs(output)
    assert [row["event"] for row in recorded] == [
        "projection.retry_scheduled",
        "projection.attempt.completed",
    ]
    assert len({row["request_id"] for row in recorded}) == 1
    assert all(
        row["rebuild_id"] == str(ticket.rebuild_id) and row["outbox_id"] == str(result.outbox_id)
        for row in recorded
    )


@pytest.mark.parametrize("fault", ["schema", "integrity"])
def test_permanent_defect_dead_stops_following_events(world, fault):
    if fault == "schema":
        with world.transaction() as c:
            c.execute("UPDATE graph_outbox SET payload=jsonb_set(payload,'{schema_version}','99')")
    service, output = step(world, FailingAdapter(ProjectionIntegrityError(SECRET)))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        result = service.run_once(leader, lock, ticket)
        assert service.run_once(leader, lock, ticket).status == "DEAD"
    assert result.status == "DEAD"
    assert stored(world, result.outbox_id)["last_error"] == "PROJECTION_PERMANENT_FAILURE"
    assert sum(row["status"] == "PENDING" for row in events(world)) == 2
    assert service.adapter.calls == (0 if fault == "schema" else 1)
    assert [row["event"] for row in logs(output)] == [
        "projection.dead",
        "projection.attempt.completed",
    ]


@pytest.mark.parametrize(
    "error",
    [ConfigurationError(SECRET), ClientError(SECRET), ValueError(SECRET), RuntimeError(SECRET)],
)
def test_unknown_stops_without_inventing_dead_and_restores_outer_context(world, error):
    service, output = step(world, FailingAdapter(error))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        with request_context(ticket.rebuild_id):
            with pytest.raises(type(error)):
                service.run_once(leader, lock, ticket)
            assert current_request_id() == str(ticket.rebuild_id)
    assert sum(row["status"] == "PROCESSING" for row in events(world)) == 1
    assert all(row["status"] != "DEAD" for row in events(world))
    (row,) = logs(output)
    assert row["outcome"] == "unknown" and row["exception_type"] == type(error).__name__
    assert current_request_id() is None


def test_final_transient_attempt_dead(world):
    with world.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=4")
    service, output = step(world, FailingAdapter(ServiceUnavailable(SECRET)))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        result = service.run_once(leader, lock, ticket)
    assert result.status == "DEAD"
    assert stored(world, result.outbox_id)["attempt_count"] == 5
    assert stored(world, result.outbox_id)["last_error"] == "PROJECTION_ATTEMPTS_EXHAUSTED"
    logs(output)


def test_failure_storage_fault_is_unknown_and_recoverable(world):
    service, output = step(world, FailingAdapter(ServiceUnavailable(SECRET)))
    with world.transaction() as c:
        c.execute(
            "CREATE FUNCTION reject_step_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-password-payload-sql'; END $$"
        )
        c.execute(
            "CREATE TRIGGER reject_step_fail BEFORE UPDATE ON graph_outbox FOR EACH ROW WHEN (NEW.status IN ('RETRYABLE','DEAD')) EXECUTE FUNCTION reject_step_fail()"
        )
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        with pytest.raises(psycopg.Error):
            service.run_once(leader, lock, ticket)
    assert sum(row["status"] == "PROCESSING" for row in events(world)) == 1
    (row,) = logs(output)
    assert row["outcome"] == "unknown"


def test_generation_changes_after_apply_fences_ack_without_false_success(world):
    def change(arguments):
        with world.transaction() as c:
            c.execute("UPDATE graph_projection_control SET active_generation=NULL")

    service, output = step(world, RecordingAdapter(change))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        result = service.run_once(leader, lock, ticket)
    assert result.status == "FENCED"
    assert stored(world, result.outbox_id)["status"] == "PROCESSING"
    (row,) = logs(output)
    assert row["outcome"] == "unknown" and row["result_code"] == "GRAPH_NOT_CURRENT"
    assert "after_status" not in row


def test_leadership_loss_does_not_become_dead(world):
    service, output = step(
        world, RecordingAdapter(lambda arguments: arguments["leadership"]._connection.close())
    )
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        with pytest.raises(GraphLeadershipLost):
            service.run_once(leader, lock, ticket)
    assert sum(row["status"] == "PROCESSING" for row in events(world)) == 1
    assert logs(output)[0]["outcome"] == "unknown"
