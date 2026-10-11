"""Real PG retry lifecycle, ownership fences and sanitized committed logs."""

import io
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from graph.test_outbox import events
from graph.test_projection_queue import queued as queued
from graph.test_projection_retry import clock, event_row
from graph.test_rebuild_queue import prepare
from graph.test_rebuild_queue import world as world
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.rebuild_queue import RebuildQueue
from linescope.logging import EventLogger, request_context


def logs(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize("attempt,delay", [(1, 1), (2, 2), (5, 16), (7, 60)])
def test_backoff_exact_attempt_and_postcommit_log(world, attempt, delay):
    output = io.StringIO()
    queue = RebuildQueue(world, max_attempts=10, logger=EventLogger(stream=output))
    with world.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=%s", (attempt - 1,))
    with graph_leadership(world) as leader, world.transaction() as lock, request_context(uuid4()):
        ticket, _ = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        before = clock(world)
        assert queue.fail(leader, lock, ticket, {**event, "payload": "secret-sql-token"})
        after = clock(world)
        saved = event_row(world, event["outbox_id"])
        assert saved["status"] == "RETRYABLE" and saved["attempt_count"] == attempt
        assert saved["processing_started_at"] is saved["processed_at"] is None
        assert (
            before + timedelta(seconds=delay)
            <= saved["next_attempt_at"]
            <= after + timedelta(seconds=delay)
        )
        assert saved["last_error"] == "PROJECTION_TRANSIENT_FAILURE"
        assert saved["payload"] == event["payload"]
        assert lock.info.transaction_status == TransactionStatus.INTRANS
        assert not queue.fail(leader, lock, ticket, event)
        assert event_row(world, event["outbox_id"]) == saved
        (row,) = logs(output)
        assert row["event"] == "projection.retry_scheduled"
        assert row["rebuild_id"] == str(ticket.rebuild_id)
        assert row["graph_generation"] == str(ticket.previous_generation)
        assert row["outbox_id"] == str(event["outbox_id"])
        assert row["request_id"] and row["attempt_count"] == attempt
        assert row["before_status"] == "PROCESSING" and row["after_status"] == "RETRYABLE"
        assert "secret-sql-token" not in output.getvalue()


@pytest.mark.parametrize(
    "permanent,attempt,code",
    [(True, 1, "PROJECTION_PERMANENT_FAILURE"), (False, 5, "PROJECTION_ATTEMPTS_EXHAUSTED")],
)
def test_permanent_or_exhausted_dead_stops_claim(world, permanent, attempt, code):
    output = io.StringIO()
    queue = RebuildQueue(world, logger=EventLogger(stream=output))
    with world.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=%s", (attempt - 1,))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        assert queue.fail(leader, lock, ticket, event, permanent=permanent)
        saved = event_row(world, event["outbox_id"])
        assert saved["status"] == "DEAD" and saved["attempt_count"] == attempt
        assert saved["last_error"] == code
        assert saved["next_attempt_at"] is saved["processing_started_at"] is None
        assert queue.claim(leader, lock, ticket).status == "DEAD"
        (row,) = logs(output)
        assert row["event"] == "projection.dead" and row["level"] == "ERROR"


@pytest.mark.parametrize(
    "damage", ["id", "generation", "flag", "attempt", "start", "applied", "dead", "missing"]
)
def test_stale_report_has_no_write_or_log(world, damage):
    output = io.StringIO()
    queue = RebuildQueue(world, logger=EventLogger(stream=output))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        with world.transaction() as c:
            if damage == "id":
                ticket = replace(ticket, rebuild_id=uuid4())
            elif damage == "generation":
                ticket = replace(ticket, previous_generation=uuid4())
            elif damage == "flag":
                c.execute("UPDATE graph_projection_control SET rebuild_flag=false")
            elif damage == "missing":
                c.execute("UPDATE graph_projection_control SET active_generation=NULL")
            elif damage == "attempt":
                event = {**event, "attempt_count": event["attempt_count"] + 1}
            elif damage == "start":
                event = {
                    **event,
                    "processing_started_at": event["processing_started_at"] - timedelta(seconds=1),
                }
            else:
                c.execute(
                    "UPDATE graph_outbox SET status=%s WHERE outbox_id=%s",
                    (damage.upper(), event["outbox_id"]),
                )
        before = events(world)
        assert not queue.fail(leader, lock, ticket, event, permanent=True)
        assert events(world) == before and not logs(output)


@pytest.mark.parametrize("shared", [None, True])
def test_failure_requires_existing_exclusive_lock(world, shared):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
    with graph_leadership(world) as leader, world.transaction() as lock:
        if shared is not None:
            acquire_graph_mutation_lock(lock, shared=shared)
        with pytest.raises(ValueError, match="exclusive"):
            queue.fail(leader, lock, ticket, event)
    assert event_row(world, event["outbox_id"])["status"] == "PROCESSING"


@pytest.mark.parametrize("max_attempts", [5, 6])
def test_lease_recovery_and_exhausted_claim_logs_actual_transitions(world, max_attempts):
    output = io.StringIO()
    queue = RebuildQueue(world, max_attempts=max_attempts, logger=EventLogger(stream=output))
    with world.transaction() as c:
        c.execute(
            "UPDATE graph_outbox SET status='PROCESSING',attempt_count=5,processing_started_at=statement_timestamp()-interval '1 hour'"
        )
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        result = queue.claim(leader, lock, ticket)
        assert result.status == ("DEAD" if max_attempts == 5 else "CLAIMED")
        assert result.event["attempt_count"] == (5 if max_attempts == 5 else 6)
        recorded = logs(output)
        retries = [row for row in recorded if row["event"] == "projection.retry_scheduled"]
        assert len(retries) == len(events(world)) - 1
        assert all(row["outbox_id"] != str(result.event["outbox_id"]) for row in retries)
        assert all(row["rebuild_id"] == str(ticket.rebuild_id) for row in recorded)
        if max_attempts == 5:
            assert recorded[-1]["event"] == "projection.dead"
            assert queue.claim(leader, lock, ticket).status == "DEAD"
            assert logs(output) == recorded
        else:
            assert recorded == retries


@pytest.mark.parametrize("loss", ["leader", "lock"])
def test_loss_before_failure_commit_rolls_back_and_logs_nothing(world, monkeypatch, loss):
    from linescope.graph import rebuild_queue as module

    output = io.StringIO()
    queue = RebuildQueue(world, logger=EventLogger(stream=output))
    original = module.fail_rebuild_graph_event

    def fail(connection, event, ticket, **arguments):
        changed = original(connection, event, ticket, **arguments)
        (leader._connection if loss == "leader" else lock).close()
        return changed

    monkeypatch.setattr(module, "fail_rebuild_graph_event", fail)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        with pytest.raises((GraphLeadershipLost, ValueError, psycopg.Error)):
            queue.fail(leader, lock, ticket, event)
    assert event_row(world, event["outbox_id"])["status"] == "PROCESSING"
    assert not logs(output)


def test_storage_failure_rolls_back_without_transition_log(world):
    output = io.StringIO()
    queue = RebuildQueue(world, logger=EventLogger(stream=output))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, _ = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        with world.transaction() as c:
            c.execute(
                "CREATE FUNCTION reject_rebuild_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'storage secret'; END $$"
            )
            c.execute(
                "CREATE TRIGGER reject_rebuild_fail BEFORE UPDATE ON graph_outbox FOR EACH ROW EXECUTE FUNCTION reject_rebuild_fail()"
            )
        with pytest.raises(psycopg.Error):
            queue.fail(leader, lock, ticket, event)
    assert event_row(world, event["outbox_id"])["status"] == "PROCESSING"
    assert not logs(output)


@pytest.mark.parametrize("permanent,attempt", [("true", 1), (True, 0), (False, True)])
def test_invalid_metadata_does_not_change_state(world, permanent, attempt):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        with pytest.raises(ValueError):
            queue.fail(
                leader, lock, ticket, {**event, "attempt_count": attempt}, permanent=permanent
            )
        assert event_row(world, event["outbox_id"])["status"] == "PROCESSING"
