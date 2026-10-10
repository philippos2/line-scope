"""Deterministic DB failure/recovery boundaries; no Neo4j apply yet."""

from datetime import timedelta
from uuid import UUID

import psycopg
import pytest
from test_outbox import events
from test_projection_queue import queued as queued

from linescope.graph_leadership import graph_leadership
from linescope.projection_queue import ProjectionQueue
from linescope.projection_state import ProjectionState


def event_row(db, identifier):
    return next(row for row in events(db) if row["outbox_id"] == identifier)


def clock(db):
    with db.transaction() as c:
        return c.execute("SELECT statement_timestamp() AS now").fetchone()["now"]


@pytest.mark.parametrize("attempt,delay", [(1, 1), (2, 2), (5, 16), (7, 60)])
def test_transient_failure_uses_bounded_backoff_without_incrementing_attempt(
    queued, attempt, delay
):
    db, _, _ = queued
    queue = ProjectionQueue(db, max_attempts=10)
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=%s", (attempt - 1,))
    with graph_leadership(db) as leader:
        claimed = queue.claim(leader)
        before = clock(db)
        assert queue.fail(leader, claimed)
        after = clock(db)
        stored = event_row(db, claimed["outbox_id"])
        assert stored["status"] == "RETRYABLE"
        assert stored["attempt_count"] == attempt
        assert stored["processing_started_at"] is None and stored["processed_at"] is None
        assert (
            before + timedelta(seconds=delay)
            <= stored["next_attempt_at"]
            <= after + timedelta(seconds=delay)
        )
        assert stored["last_error"] == "PROJECTION_TRANSIENT_FAILURE"
        assert stored["payload"] == claimed["payload"]
        assert queue.fail(leader, claimed) is False
        assert event_row(db, claimed["outbox_id"]) == stored


@pytest.mark.parametrize(
    "permanent,attempt,code",
    [(True, 1, "PROJECTION_PERMANENT_FAILURE"), (False, 5, "PROJECTION_ATTEMPTS_EXHAUSTED")],
)
def test_permanent_or_final_attempt_is_dead_and_stops_later_claims(
    queued, permanent, attempt, code
):
    db, _, queue = queued
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=%s", (attempt - 1,))
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
            (UUID(int=41),),
        )
    assert ProjectionState(db).observe().status == "LAGGING"
    with graph_leadership(db) as leader:
        claimed = queue.claim(leader)
        assert queue.fail(leader, claimed, permanent=permanent)
        assert queue.claim(leader) is None
    stored = event_row(db, claimed["outbox_id"])
    assert stored["status"] == "DEAD" and stored["attempt_count"] == attempt
    assert stored["last_error"] == code
    assert stored["next_attempt_at"] is stored["processing_started_at"] is None
    assert ProjectionState(db).observe().status == "ERROR"
    assert sum(row["status"] == "PENDING" for row in events(db)) == 2


def test_old_failure_report_cannot_retire_reclaimed_attempt(queued):
    db, _, queue = queued
    with graph_leadership(db) as leader:
        old = queue.claim(leader)
        assert queue.fail(leader, old)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET status='APPLIED' WHERE outbox_id<>%s", (old["outbox_id"],)
            )
            c.execute(
                "UPDATE graph_outbox SET next_attempt_at=statement_timestamp()-interval '1 second' WHERE outbox_id=%s",
                (old["outbox_id"],),
            )
        new = queue.claim(leader)
        assert new["outbox_id"] == old["outbox_id"] and new["attempt_count"] == 2
        before = event_row(db, new["outbox_id"])
        assert queue.fail(leader, old, permanent=True) is False
        assert (
            queue.fail(
                leader,
                {
                    **new,
                    "processing_started_at": new["processing_started_at"] - timedelta(seconds=1),
                },
            )
            is False
        )
        assert event_row(db, new["outbox_id"]) == before


@pytest.mark.parametrize("status", ["APPLIED", "DEAD"])
def test_failure_report_cannot_reopen_terminal_event(queued, status):
    db, _, queue = queued
    with graph_leadership(db) as leader:
        claimed = queue.claim(leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET status=%s WHERE outbox_id=%s",
                (status, claimed["outbox_id"]),
            )
        before = events(db)
        assert queue.fail(leader, claimed) is False
        assert events(db) == before


def test_lease_recovery_changes_only_expired_processing_and_preserves_attempt(queued):
    db, _, queue = queued
    with graph_leadership(db) as leader:
        expired = queue.claim(leader)
        fresh = queue.claim(leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                (expired["outbox_id"],),
            )
        fresh_before = event_row(db, fresh["outbox_id"])
        assert queue.recover_expired(leader) == [expired["outbox_id"]]
        restored = event_row(db, expired["outbox_id"])
        assert restored["status"] == "RETRYABLE" and restored["attempt_count"] == 1
        assert restored["last_error"] == "PROJECTION_LEASE_EXPIRED"
        assert restored["processing_started_at"] is None
        assert restored["next_attempt_at"] <= clock(db)
        assert restored["payload"] == expired["payload"]
        assert event_row(db, fresh["outbox_id"]) == fresh_before
        assert queue.recover_expired(leader) == []
        assert queue.fail(leader, expired) is False


@pytest.mark.parametrize("gate", ["rebuilding", "missing_control"])
def test_rebuild_gate_prevents_normal_lease_recovery(queued, gate):
    db, _, queue = queued
    with graph_leadership(db) as leader:
        claimed = queue.claim(leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                (claimed["outbox_id"],),
            )
            c.execute(
                "UPDATE graph_projection_control SET rebuild_flag=true"
                if gate == "rebuilding"
                else "DELETE FROM graph_projection_control"
            )
        before = events(db)
        assert queue.recover_expired(leader) == []
        assert events(db) == before


def test_recovered_last_attempt_is_dead_without_a_sixth_processing_attempt(queued):
    db, _, queue = queued
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET attempt_count=4")
    with graph_leadership(db) as leader:
        claimed = queue.claim(leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                (claimed["outbox_id"],),
            )
        assert queue.recover_expired(leader) == [claimed["outbox_id"]]
        assert event_row(db, claimed["outbox_id"])["status"] == "RETRYABLE"
        assert queue.claim(leader) is None
        stored = event_row(db, claimed["outbox_id"])
        assert stored["status"] == "DEAD" and stored["attempt_count"] == 5
        assert stored["last_error"] == "PROJECTION_ATTEMPTS_EXHAUSTED"
        assert queue.claim(leader) is None


@pytest.mark.parametrize("operation", ["fail", "recover"])
def test_storage_fault_rolls_back_failure_or_recovery(queued, operation):
    db, _, queue = queued
    with graph_leadership(db) as leader:
        claimed = queue.claim(leader)
        with db.transaction() as c:
            if operation == "recover":
                c.execute(
                    "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                    (claimed["outbox_id"],),
                )
            c.execute(
                "CREATE FUNCTION fail_queue_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private fault'; END $$"
            )
            c.execute(
                "CREATE TRIGGER fail_queue_update BEFORE UPDATE ON graph_outbox FOR EACH ROW EXECUTE FUNCTION fail_queue_update()"
            )
        before = events(db)
        with pytest.raises(psycopg.Error):
            if operation == "fail":
                queue.fail(leader, claimed)
            else:
                queue.recover_expired(leader)
        assert events(db) == before
        leader.require()


@pytest.mark.parametrize(
    "options",
    [{"lease_seconds": 0}, {"max_attempts": 0}, {"lease_seconds": True}, {"max_attempts": 1.5}],
)
def test_invalid_worker_limits_are_rejected_before_db_access(options):
    with pytest.raises(ValueError):
        ProjectionQueue(object(), **options)
