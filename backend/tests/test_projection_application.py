"""Real PG application fencing; RecordingAdapter is explicitly not Neo4j."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import psycopg
import pytest
from test_outbox import events
from test_projection_queue import queued as queued

from linescope.database import Database
from linescope.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph_locks import acquire_graph_mutation_lock
from linescope.projection_application import ProjectionApplication

GENERATION = UUID(int=81)


class RecordingAdapter:
    def __init__(self, action=None):
        self.calls = []
        self.action = action

    def apply(self, **arguments):
        self.calls.append(arguments)
        if self.action:
            self.action(arguments)


@pytest.fixture
def application(queued):
    db, _, queue = queued
    with db.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
            (GENERATION,),
        )
    return db, queue, ProjectionApplication(db)


def stored(db, event):
    return next(row for row in events(db) if row["outbox_id"] == event["outbox_id"])


def test_adapter_commit_precedes_applied_and_mutation_lock_covers_both(application):
    db, queue, service = application
    contender = Database(replace(db.settings, lock_ms=50, statement_ms=1000))
    with graph_leadership(db) as leader:
        event = queue.claim(leader)

        def check(arguments):
            assert stored(db, event)["status"] == "PROCESSING"
            assert arguments["generation"] == GENERATION
            assert arguments["payload"] == event["payload"]
            arguments["leadership"].require()
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with contender.transaction() as c:
                    acquire_graph_mutation_lock(c, shared=True)
            # No event/control row lock is retained during adapter I/O.
            with contender.transaction() as c:
                c.execute("SELECT outbox_id FROM graph_outbox FOR UPDATE")
                c.execute("SELECT control_id FROM graph_projection_control FOR UPDATE")

        adapter = RecordingAdapter(check)
        # Caller payload is not authoritative; use the saved DB state.
        assert service.apply(leader, {**event, "payload": {}}, adapter)
        row = stored(db, event)
        assert row["status"] == "APPLIED" and row["processed_at"] is not None
        assert row["attempt_count"] == 1
        assert row["processing_started_at"] is row["next_attempt_at"] is row["last_error"] is None
        assert not service.apply(leader, event, adapter)
        assert len(adapter.calls) == 1
    with contender.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)


@pytest.mark.parametrize(
    "gate",
    [
        "expired",
        "stale_attempt",
        "stale_start",
        "terminal",
        "dead",
        "rebuilding",
        "missing_control",
        "missing_generation",
        "fatal",
    ],
)
def test_gate_prevents_adapter_and_acknowledgement(application, gate):
    db, queue, service = application
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        with db.transaction() as c:
            if gate == "expired":
                c.execute(
                    "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                    (event["outbox_id"],),
                )
            elif gate == "stale_attempt":
                event = {**event, "attempt_count": event["attempt_count"] + 1}
            elif gate == "stale_start":
                event = {
                    **event,
                    "processing_started_at": event["processing_started_at"] - timedelta(seconds=1),
                }
            elif gate == "terminal":
                c.execute(
                    "UPDATE graph_outbox SET status='APPLIED' WHERE outbox_id=%s",
                    (event["outbox_id"],),
                )
            elif gate == "dead":
                c.execute(
                    "UPDATE graph_outbox SET status='DEAD' WHERE outbox_id<>%s",
                    (event["outbox_id"],),
                )
            elif gate == "rebuilding":
                c.execute("UPDATE graph_projection_control SET rebuild_flag=true")
            elif gate == "missing_control":
                c.execute("DELETE FROM graph_projection_control")
            elif gate == "missing_generation":
                c.execute("UPDATE graph_projection_control SET active_generation=NULL")
            else:
                c.execute("UPDATE graph_projection_control SET fatal_error='TEST_FAULT'")
        if gate == "expired":
            event = {**event, "processing_started_at": stored(db, event)["processing_started_at"]}
        before = events(db)
        adapter = RecordingAdapter()
        assert not service.apply(leader, event, adapter)
        assert not adapter.calls and events(db) == before


@pytest.mark.parametrize("change", ["generation", "rebuilding", "dead", "attempt", "expired"])
def test_gate_is_rechecked_after_adapter_commit(application, change):
    db, queue, service = application
    with graph_leadership(db) as leader:
        event = queue.claim(leader)

        def change_state(arguments):
            with db.transaction() as c:
                if change == "generation":
                    c.execute(
                        "UPDATE graph_projection_control SET active_generation=%s", (UUID(int=82),)
                    )
                elif change == "rebuilding":
                    c.execute("UPDATE graph_projection_control SET rebuild_flag=true")
                elif change == "dead":
                    c.execute(
                        "UPDATE graph_outbox SET status='DEAD' WHERE outbox_id<>%s",
                        (event["outbox_id"],),
                    )
                elif change == "attempt":
                    c.execute(
                        "UPDATE graph_outbox SET attempt_count=attempt_count+1 WHERE outbox_id=%s",
                        (event["outbox_id"],),
                    )
                else:
                    c.execute(
                        "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                        (event["outbox_id"],),
                    )

        assert not service.apply(leader, event, RecordingAdapter(change_state))
        assert stored(db, event)["status"] == "PROCESSING"
        assert stored(db, event)["processed_at"] is None


def test_adapter_failure_never_marks_applied_and_releases_lock(application):
    db, queue, service = application

    def fail(arguments):
        raise RuntimeError("adapter fault")

    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        before = events(db)
        with pytest.raises(RuntimeError, match="adapter fault"):
            service.apply(leader, event, RecordingAdapter(fail))
        assert events(db) == before
        with db.transaction() as c:
            acquire_graph_mutation_lock(c, shared=False)


def test_ack_failure_leaves_committed_claim_replayable(application):
    db, queue, service = application

    def fail_ack(arguments):
        with db.transaction() as c:
            c.execute(
                "CREATE FUNCTION reject_ack() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'ack fault'; END $$"
            )
            c.execute(
                "CREATE TRIGGER reject_ack BEFORE UPDATE ON graph_outbox FOR EACH ROW EXECUTE FUNCTION reject_ack()"
            )

    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        adapter = RecordingAdapter(fail_ack)
        with pytest.raises(psycopg.Error):
            service.apply(leader, event, adapter)
        assert len(adapter.calls) == 1
        row = stored(db, event)
        assert row["status"] == "PROCESSING" and row["processed_at"] is None
        with db.transaction() as c:
            c.execute("DROP TRIGGER reject_ack ON graph_outbox")
        # The real adapter must make this replay idempotent; this test only
        # checks PG lifecycle and callback ordering, not Graph correctness.
        assert service.apply(leader, event, RecordingAdapter())


@pytest.mark.parametrize("corruption", ["schema", "aggregate"])
def test_invalid_saved_payload_is_rejected_before_adapter(application, corruption):
    db, queue, service = application
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        with db.transaction() as c:
            if corruption == "schema":
                c.execute(
                    "UPDATE graph_outbox SET payload=jsonb_set(payload,'{schema_version}','99') WHERE outbox_id=%s",
                    (event["outbox_id"],),
                )
            else:
                c.execute(
                    "UPDATE graph_outbox SET aggregate_id=%s WHERE outbox_id=%s",
                    (
                        UUID(int=999),
                        event["outbox_id"],
                    ),
                )
        before = events(db)
        adapter = RecordingAdapter()
        with pytest.raises(ValueError):
            service.apply(leader, event, adapter)
        assert not adapter.calls and events(db) == before


def test_leadership_loss_after_adapter_prevents_ack(application):
    db, queue, service = application
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        with pytest.raises(GraphLeadershipLost):
            service.apply(
                leader, event, RecordingAdapter(lambda arguments: leader._connection.close())
            )
        assert stored(db, event)["status"] == "PROCESSING"
        assert stored(db, event)["processed_at"] is None


def test_acknowledgement_keeps_mutation_lock_until_commit(application, monkeypatch):
    from linescope import projection_application as module

    db, queue, service = application
    contender = Database(replace(db.settings, lock_ms=50, statement_ms=1000))
    original = module.acknowledge_graph_application
    observed = []

    def acknowledge(connection, event, lease_seconds, generation):
        changed = original(connection, event, lease_seconds, generation)
        assert stored(db, event)["status"] == "PROCESSING"  # APPLIED is not committed yet.
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with contender.transaction() as c:
                acquire_graph_mutation_lock(c, shared=True)
        observed.append(changed)
        return changed

    monkeypatch.setattr(module, "acknowledge_graph_application", acknowledge)
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        assert service.apply(leader, event, RecordingAdapter())
    assert observed == [True] and stored(db, event)["status"] == "APPLIED"


def test_mutation_lock_timeout_does_not_call_adapter_or_ack(application):
    db, queue, _ = application
    service = ProjectionApplication(Database(replace(db.settings, lock_ms=50, statement_ms=1000)))
    adapter = RecordingAdapter()
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        before = events(db)
        with db.transaction() as holder:
            acquire_graph_mutation_lock(holder, shared=True)
            with pytest.raises(psycopg.errors.LockNotAvailable):
                service.apply(leader, event, adapter)
        assert not adapter.calls and events(db) == before


def test_lost_leadership_before_application_cannot_call_adapter(application):
    db, queue, service = application
    adapter = RecordingAdapter()
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        leader._connection.close()
        with pytest.raises(GraphLeadershipLost):
            service.apply(leader, event, adapter)
    assert not adapter.calls and stored(db, event)["status"] == "PROCESSING"


def test_lost_mutation_connection_after_adapter_prevents_ack(application, monkeypatch):
    from linescope import projection_application as module

    db, queue, service = application
    connections = []
    original = module.acquire_graph_mutation_lock

    def acquire(connection, *, shared):
        original(connection, shared=shared)
        connections.append(connection)

    monkeypatch.setattr(module, "acquire_graph_mutation_lock", acquire)
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        with pytest.raises((ValueError, psycopg.Error)):
            service.apply(leader, event, RecordingAdapter(lambda arguments: connections[0].close()))
        assert stored(db, event)["status"] == "PROCESSING"
        assert stored(db, event)["processed_at"] is None


def test_leader_loss_before_ack_commit_rolls_back_applied(application, monkeypatch):
    from linescope import projection_application as module

    db, queue, service = application
    original = module.acknowledge_graph_application

    def acknowledge(connection, event, lease_seconds, generation):
        changed = original(connection, event, lease_seconds, generation)
        leader._connection.close()
        return changed

    monkeypatch.setattr(module, "acknowledge_graph_application", acknowledge)
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        with pytest.raises(GraphLeadershipLost):
            service.apply(leader, event, RecordingAdapter())
    assert stored(db, event)["status"] == "PROCESSING"
    assert stored(db, event)["processed_at"] is None
