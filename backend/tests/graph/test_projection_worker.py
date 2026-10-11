"""Single worker iteration: real PG/Neo4j and named failure boundaries."""

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
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.projection_state import ProjectionState
from linescope.graph.projection_worker import ProjectionWorker
from linescope.logging import EventLogger, current_request_id

SECRET = "private-password-payload-sql"


class FailingAdapter:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def apply(self, **arguments):
        self.calls += 1
        raise self.error


def ready(db, generation=UUID(int=301)):
    with db.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
            (generation,),
        )


def worker(db, adapter):
    output = io.StringIO()
    return ProjectionWorker(db, adapter, logger=EventLogger(stream=output)), output


def entries(output):
    assert SECRET not in output.getvalue()
    return [json.loads(line) for line in output.getvalue().splitlines()]


def stored(db, identifier):
    return next(row for row in events(db) if row["outbox_id"] == identifier)


def test_single_iteration_applies_one_event_and_idle_does_not_manufacture_attempt(graph, queued):
    db, _, _ = queued
    _, generation, adapter = graph
    ready(db, generation)
    for event in events(db):
        seed_endpoints(graph, event["payload"])
    service, output = worker(db, adapter)
    with graph_leadership(db) as leader:
        first = service.run_once(leader)
        assert first.status == "APPLIED"
        assert sum(row["status"] == "APPLIED" for row in events(db)) == 1
        assert len(facts(graph)[0]) == 1
        assert service.run_once(leader).status == "APPLIED"
        assert service.run_once(leader).status == "APPLIED"
        assert service.run_once(leader).status == "IDLE"
        leader.require()
    assert ProjectionState(db).observe().status == "CURRENT"
    logs = entries(output)
    assert len(logs) == 3 and all(row["event"] == "projection.attempt.completed" for row in logs)
    assert all(row["after_status"] == "APPLIED" and row["result_code"] == "OK" for row in logs)
    assert len({row["request_id"] for row in logs}) == 3
    assert current_request_id() is None


@pytest.mark.parametrize(
    "gate", ["missing_control", "missing_generation", "fatal", "rebuilding", "dead"]
)
def test_blocked_graph_state_never_consumes_attempts_or_calls_adapter(queued, gate):
    db, _, _ = queued
    ready(db)
    with db.transaction() as c:
        if gate == "missing_control":
            c.execute("DELETE FROM graph_projection_control")
        elif gate == "missing_generation":
            c.execute("UPDATE graph_projection_control SET active_generation=NULL")
        elif gate == "fatal":
            c.execute("UPDATE graph_projection_control SET fatal_error='FAULT'")
        elif gate == "rebuilding":
            c.execute("UPDATE graph_projection_control SET rebuild_flag=true")
        else:
            c.execute("UPDATE graph_outbox SET status='DEAD'")
    before = events(db)
    adapter = FailingAdapter(RuntimeError(SECRET))
    service, output = worker(db, adapter)
    with graph_leadership(db) as leader:
        result = service.run_once(leader)
    assert result.status == "BLOCKED" and result.outbox_id is None
    assert events(db) == before and adapter.calls == 0 and entries(output) == []


@pytest.mark.parametrize(
    "error",
    [
        ServiceUnavailable(SECRET),
        TransientError(SECRET),
        psycopg.OperationalError(SECRET),
        psycopg.errors.QueryCanceled(SECRET),
    ],
)
def test_known_transient_failure_is_saved_once_with_safe_correlated_logs(queued, error):
    db, _, _ = queued
    ready(db)
    adapter = FailingAdapter(error)
    service, output = worker(db, adapter)
    with graph_leadership(db) as leader:
        result = service.run_once(leader)
    assert result.status == "RETRYABLE" and adapter.calls == 1
    row = stored(db, result.outbox_id)
    assert row["status"] == "RETRYABLE" and row["attempt_count"] == 1
    assert row["last_error"] == "PROJECTION_TRANSIENT_FAILURE" and row["processed_at"] is None
    logs = entries(output)
    assert [row["event"] for row in logs] == [
        "projection.retry_scheduled",
        "projection.attempt.completed",
    ]
    assert logs[0]["request_id"] == logs[1]["request_id"]
    assert all(
        row["outbox_id"] == str(result.outbox_id) and row["attempt_count"] == 1 for row in logs
    )


def test_bad_saved_payload_becomes_dead_and_stops_later_events(queued):
    db, _, _ = queued
    ready(db)
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET payload=jsonb_set(payload,'{schema_version}','99')")
    adapter = FailingAdapter(RuntimeError(SECRET))
    service, output = worker(db, adapter)
    with graph_leadership(db) as leader:
        result = service.run_once(leader)
        assert service.run_once(leader).status == "BLOCKED"
    assert result.status == "DEAD" and adapter.calls == 0
    row = stored(db, result.outbox_id)
    assert row["last_error"] == "PROJECTION_PERMANENT_FAILURE"
    assert sum(row["status"] == "PENDING" for row in events(db)) == 2
    assert ProjectionState(db).observe().status == "ERROR"
    assert [row["event"] for row in entries(output)] == [
        "projection.dead",
        "projection.attempt.completed",
    ]


def test_same_version_different_graph_hash_is_permanent(graph, queued):
    db, _, _ = queued
    _, generation, adapter = graph
    ready(db, generation)
    for event in events(db):
        payload = dict(event["payload"])
        payload["state"] = {**payload["state"], "active": not payload["state"]["active"]}
        seed_endpoints(graph, payload)
        adapter.apply(
            generation=generation,
            outbox_id=event["outbox_id"],
            payload=payload,
            leadership=type("Leader", (), {"require": lambda self: None})(),
        )
    before = facts(graph)
    service, output = worker(db, adapter)
    with graph_leadership(db) as leader:
        result = service.run_once(leader)
    assert result.status == "DEAD" and facts(graph) == before
    assert stored(db, result.outbox_id)["last_error"] == "PROJECTION_PERMANENT_FAILURE"
    entries(output)


@pytest.mark.parametrize(
    "error",
    [ConfigurationError(SECRET), ClientError(SECRET), ValueError(SECRET), RuntimeError(SECRET)],
)
def test_unknown_or_configuration_failure_stops_without_inventing_dead(queued, error):
    db, _, _ = queued
    ready(db)
    service, output = worker(db, FailingAdapter(error))
    with graph_leadership(db) as leader, pytest.raises(type(error)):
        service.run_once(leader)
    assert sum(row["status"] == "PROCESSING" for row in events(db)) == 1
    assert all(row["status"] != "DEAD" for row in events(db))
    logs = entries(output)
    assert len(logs) == 1 and logs[0]["outcome"] == "unknown"
    assert logs[0]["exception_type"] == type(error).__name__
    assert current_request_id() is None


def test_final_transient_failure_is_dead(queued):
    db, _, _ = queued
    ready(db)
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=4")
    service, output = worker(db, FailingAdapter(ServiceUnavailable(SECRET)))
    with graph_leadership(db) as leader:
        result = service.run_once(leader)
        assert service.run_once(leader).status == "BLOCKED"
    row = stored(db, result.outbox_id)
    assert result.status == "DEAD" and row["attempt_count"] == 5
    assert row["last_error"] == "PROJECTION_ATTEMPTS_EXHAUSTED"
    assert entries(output)[0]["event"] == "projection.dead"


def test_recovered_final_attempt_is_retired_and_logged_without_an_extra_attempt(queued):
    db, _, queue = queued
    ready(db)
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=4")
    service, output = worker(db, FailingAdapter(RuntimeError(SECRET)))
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                (event["outbox_id"],),
            )
        assert service.run_once(leader).status == "BLOCKED"
    row = stored(db, event["outbox_id"])
    assert row["status"] == "DEAD" and row["attempt_count"] == 5
    logs = entries(output)
    assert [row["event"] for row in logs] == ["projection.retry_scheduled", "projection.dead"]
    assert logs[0]["before_status"] == "PROCESSING" and logs[0]["after_status"] == "RETRYABLE"
    assert logs[1]["after_status"] == "DEAD"


def test_failure_persistence_fault_remains_unknown_and_recoverable(queued):
    db, _, _ = queued
    ready(db)
    with db.transaction() as c:
        c.execute(
            "CREATE FUNCTION reject_worker_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-password-payload-sql'; END $$"
        )
        c.execute(
            "CREATE TRIGGER reject_worker_failure BEFORE UPDATE ON graph_outbox FOR EACH ROW WHEN (NEW.status IN ('RETRYABLE','DEAD')) EXECUTE FUNCTION reject_worker_failure()"
        )
    service, output = worker(db, FailingAdapter(ServiceUnavailable(SECRET)))
    with graph_leadership(db) as leader, pytest.raises(psycopg.Error):
        service.run_once(leader)
    assert sum(row["status"] == "PROCESSING" for row in events(db)) == 1
    assert [row["outcome"] for row in entries(output)] == ["unknown"]


def test_graph_commit_then_transient_ack_fault_retries_idempotently(graph, queued, monkeypatch):
    from linescope.graph import projection_application as module

    db, _, _ = queued
    _, generation, adapter = graph
    ready(db, generation)
    for event in events(db):
        seed_endpoints(graph, event["payload"])
    service, output = worker(db, adapter)
    original = module.acknowledge_graph_application

    def fail(*arguments):
        original(*arguments)
        raise psycopg.OperationalError(SECRET)

    monkeypatch.setattr(module, "acknowledge_graph_application", fail)
    with graph_leadership(db) as leader:
        first = service.run_once(leader)
        assert first.status == "RETRYABLE"
        before = facts(graph)
        assert len(before[0]) == 1
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET status='APPLIED' WHERE outbox_id<>%s", (first.outbox_id,)
            )
            c.execute(
                "UPDATE graph_outbox SET next_attempt_at=statement_timestamp()-interval '1 second' WHERE outbox_id=%s",
                (first.outbox_id,),
            )
        monkeypatch.setattr(module, "acknowledge_graph_application", original)
        second = service.run_once(leader)
    assert second.status == "APPLIED" and second.outbox_id == first.outbox_id
    assert facts(graph) == before and stored(db, first.outbox_id)["attempt_count"] == 2
    logs = entries(output)
    assert logs[0]["request_id"] != logs[-1]["request_id"]
    assert logs[-1]["result_code"] == "OK"


def test_leadership_loss_does_not_schedule_retry_from_the_old_session(queued):
    db, _, _ = queued
    ready(db)

    class LostAdapter:
        def apply(self, **arguments):
            arguments["leadership"]._connection.close()
            raise ServiceUnavailable(SECRET)

    service, output = worker(db, LostAdapter())
    with graph_leadership(db) as leader, pytest.raises(GraphLeadershipLost):
        service.run_once(leader)
    assert sum(row["status"] == "PROCESSING" for row in events(db)) == 1
    assert entries(output)[0]["outcome"] == "unknown"


def test_missing_neo4j_generation_is_retryable_not_a_payload_defect(graph, queued):
    db, _, _ = queued
    driver, generation, adapter = graph
    ready(db, generation)
    with driver.session() as session:
        session.run(
            "MATCH (g:LineScopeGeneration {generation:$generation}) DELETE g", generation=generation
        ).consume()
    service, output = worker(db, adapter)
    with graph_leadership(db) as leader:
        result = service.run_once(leader)
    assert result.status == "RETRYABLE" and facts(graph) == ([], [])
    assert stored(db, result.outbox_id)["last_error"] == "PROJECTION_TRANSIENT_FAILURE"
    entries(output)


def test_changed_generation_is_fenced_without_inventing_retry_or_applied(graph, queued):
    db, _, _ = queued
    _, generation, real_adapter = graph
    ready(db, generation)
    for event in events(db):
        seed_endpoints(graph, event["payload"])

    class ChangedAdapter:
        def apply(self, **arguments):
            real_adapter.apply(**arguments)
            ready(db, UUID(int=399))

    service, output = worker(db, ChangedAdapter())
    with graph_leadership(db) as leader:
        result = service.run_once(leader)
    assert result.status == "FENCED" and stored(db, result.outbox_id)["status"] == "PROCESSING"
    logs = entries(output)
    assert len(logs) == 1 and logs[0]["outcome"] == "unknown"
    assert "after_status" not in logs[0]


@pytest.mark.parametrize("timeout", [30, 31])
def test_real_adapter_timeout_must_fit_lease_before_any_connection(timeout):
    from linescope.graph.neo4j_projection import Neo4jProjection

    with pytest.raises(ValueError, match="shorter"):
        ProjectionWorker(object(), Neo4jProjection(None, timeout_seconds=timeout))
