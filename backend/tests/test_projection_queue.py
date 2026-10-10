"""Real PostgreSQL claim boundary before mutation locks or Neo4j application."""

from uuid import UUID

import psycopg
import pytest
from test_outbox import events
from test_outbox import world as saved_fixture

from linescope.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph_locks import acquire_graph_mutation_lock
from linescope.outbox import enqueue_graph_target
from linescope.projection_queue import ProjectionQueue


@pytest.fixture
def queued(db):
    db, _, saved = saved_fixture.__wrapped__(db)
    with db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        for target in saved.snapshot.data["targets"]:
            enqueue_graph_target(c, saved.update_request_id, target)
    return db, saved, ProjectionQueue(db)


def ordered(db):
    with db.transaction() as c:
        return c.execute("SELECT * FROM graph_outbox ORDER BY created_at,outbox_id").fetchall()


def test_claim_commits_exact_event_payload_and_attempt_before_application(queued):
    db, _, queue = queued
    before = ordered(db)
    with graph_leadership(db) as leader:
        claimed = queue.claim(leader)
        leader.require()
    assert claimed["outbox_id"] == before[0]["outbox_id"]
    assert claimed["payload"] == before[0]["payload"]
    assert claimed["attempt_count"] == 1
    assert claimed["processing_started_at"].tzinfo is not None
    after = next(e for e in events(db) if e["outbox_id"] == claimed["outbox_id"])
    assert after["status"] == "PROCESSING" and after["processed_at"] is None
    assert after["processing_started_at"] == claimed["processing_started_at"]
    assert sum(e["status"] == "PENDING" for e in events(db)) == 2


def test_pending_events_are_claimed_once_and_exhaustion_returns_none(queued):
    db, _, queue = queued
    expected = [e["outbox_id"] for e in ordered(db)]
    with graph_leadership(db) as leader:
        assert [queue.claim(leader)["outbox_id"] for _ in expected] == expected
        assert queue.claim(leader) is None
    assert all(e["status"] == "PROCESSING" and e["attempt_count"] == 1 for e in events(db))


@pytest.mark.parametrize("status", ["PROCESSING", "APPLIED", "DEAD"])
def test_ineligible_terminal_or_inflight_events_are_not_reclaimed(queued, status):
    db, _, queue = queued
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET status=%s", (status,))
    before = events(db)
    with graph_leadership(db) as leader:
        assert queue.claim(leader) is None
    assert events(db) == before


def test_retry_due_time_and_attempt_increment_use_database_clock(queued):
    db, _, queue = queued
    selected = ordered(db)[0]["outbox_id"]
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET status='APPLIED'")
        c.execute(
            "UPDATE graph_outbox SET status='RETRYABLE',attempt_count=2,next_attempt_at=statement_timestamp()+interval '1 hour' WHERE outbox_id=%s",
            (selected,),
        )
    with graph_leadership(db) as leader:
        assert queue.claim(leader) is None
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_outbox SET next_attempt_at=statement_timestamp()-interval '1 second' WHERE outbox_id=%s",
                (selected,),
            )
        result = queue.claim(leader)
    assert result["outbox_id"] == selected and result["attempt_count"] == 3


@pytest.mark.parametrize("gate", ["dead", "rebuilding", "missing_control"])
def test_stop_gate_preserves_all_other_pending_events(queued, gate):
    db, _, queue = queued
    with db.transaction() as c:
        if gate == "dead":
            c.execute(
                "UPDATE graph_outbox SET status='DEAD' WHERE outbox_id=%s",
                (ordered(db)[0]["outbox_id"],),
            )
        elif gate == "rebuilding":
            c.execute("UPDATE graph_projection_control SET rebuild_flag=true")
        else:
            c.execute("DELETE FROM graph_projection_control")
    before = events(db)
    with graph_leadership(db) as leader:
        assert queue.claim(leader) is None
    assert events(db) == before


def test_claim_does_not_wait_for_mutation_or_control_row_lock(queued):
    db, _, queue = queued
    with graph_leadership(db) as leader, db.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=False)
        holder.execute(
            "SELECT control_id FROM graph_projection_control WHERE control_id=1 FOR UPDATE"
        )
        assert queue.claim(leader) is not None


def test_inserted_but_uncommitted_event_is_not_visible_and_late_lower_id_is_claimed(queued):
    db, saved, queue = queued
    # Reset only fixture events; use the same saved target to stage one event.
    with db.transaction() as c:
        c.execute("DELETE FROM graph_outbox")
    with graph_leadership(db) as leader:
        with db.transaction() as writer:
            acquire_graph_mutation_lock(writer, shared=False)
            identifier = enqueue_graph_target(
                writer, saved.update_request_id, saved.snapshot.data["targets"][0]
            )
            writer.execute(
                "UPDATE graph_outbox SET outbox_id=%s,created_at=statement_timestamp()-interval '1 day' WHERE outbox_id=%s",
                (UUID(int=1), identifier),
            )
            assert queue.claim(leader) is None
        assert queue.claim(leader)["outbox_id"] == UUID(int=1)


@pytest.mark.parametrize("lost_at,processing", [(2, 0), (3, 1)])
def test_leadership_loss_before_or_after_commit_preserves_recoverable_boundary(
    queued, monkeypatch, lost_at, processing
):
    db, _, queue = queued
    with graph_leadership(db) as leader:
        require = leader.require
        calls = 0

        def checked():
            nonlocal calls
            calls += 1
            if calls == lost_at:
                leader._connection.close()
            require()

        monkeypatch.setattr(leader, "require", checked)
        with pytest.raises(GraphLeadershipLost):
            queue.claim(leader)
    assert sum(e["status"] == "PROCESSING" for e in events(db)) == processing
    assert sum(e["attempt_count"] for e in events(db)) == processing


def test_claim_database_failure_rolls_back_processing_and_attempt(queued):
    db, _, queue = queued
    with db.transaction() as c:
        c.execute(
            "CREATE FUNCTION fail_claim() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'claim fault'; END $$"
        )
        c.execute(
            "CREATE TRIGGER fail_claim BEFORE UPDATE ON graph_outbox FOR EACH ROW EXECUTE FUNCTION fail_claim()"
        )
    before = events(db)
    with graph_leadership(db) as leader:
        with pytest.raises(psycopg.Error):
            queue.claim(leader)
        leader.require()
    assert events(db) == before
