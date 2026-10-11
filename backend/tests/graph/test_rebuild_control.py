from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from psycopg.pq import TransactionStatus

from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_projection_queue import queued as queued
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.neo4j_projection import GraphGenerationUnavailable, ProjectionIntegrityError
from linescope.graph.projection_state import ProjectionState
from linescope.graph.rebuild_control import RebuildControl, RebuildControlRejected
from linescope.graph.rebuild_snapshot import RebuildSnapshot


@pytest.fixture
def store(db):
    db.migrate()
    return db


def row(db):
    with db.transaction() as connection:
        return connection.execute("SELECT * FROM graph_projection_control").fetchone()


def verified(target, leader):
    _, generation, adapter = target
    result = adapter.build(
        generation=generation,
        snapshot=RebuildSnapshot(datetime.now(timezone.utc), (), ()),
        leadership=leader,
    )
    return result, adapter


def test_initial_fatal_error_can_enter_rebuild_and_publish_verified_generation(store, target):
    control = RebuildControl(store)
    with graph_leadership(store) as leader:
        ticket = control.begin(leader)
        assert ticket.previous_generation is None
        assert ProjectionState(store).observe().status == "REBUILDING"
        with store.transaction() as lock:
            acquire_graph_mutation_lock(lock, shared=False)
            result, adapter = verified(target, leader)
            control.publish(leader, lock, ticket, result, adapter)
            assert lock.info.transaction_status == TransactionStatus.INTRANS
            assert row(store)["active_generation"] == UUID(result.generation)
            assert ProjectionState(store).observe().status == "CURRENT"
        assert not control.fail(leader, ticket)
    saved = row(store)
    assert saved["fatal_error"] is None and not saved["rebuild_flag"]


def test_failure_preserves_old_generation_and_records_fixed_error(store):
    previous = uuid4()
    with store.transaction() as connection:
        connection.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error='OLD_ERROR'",
            (previous,),
        )
    with graph_leadership(store) as leader:
        control = RebuildControl(store)
        ticket = control.begin(leader)
        assert ticket.previous_generation == previous
        assert control.fail(leader, ticket)
        assert not control.fail(leader, ticket)
    saved = row(store)
    assert saved["active_generation"] == previous
    assert saved["fatal_error"] == "REBUILD_FAILED"
    assert not saved["rebuild_flag"]
    assert ProjectionState(store).observe().status == "ERROR"


def test_existing_flag_requires_recovery_and_is_not_overwritten(store):
    with graph_leadership(store) as leader:
        control = RebuildControl(store)
        ticket = control.begin(leader)
        before = row(store)
        with pytest.raises(RebuildControlRejected, match="recovery"):
            control.begin(leader)
        assert row(store) == before
        assert control.fail(leader, ticket)


@pytest.mark.parametrize("status", ["PENDING", "PROCESSING", "RETRYABLE", "DEAD"])
def test_any_undrained_event_prevents_publication(queued, target, status):
    db, _, _ = queued
    with db.transaction() as connection:
        connection.execute("UPDATE graph_outbox SET status=%s", (status,))
    with graph_leadership(db) as leader:
        control = RebuildControl(db)
        ticket = control.begin(leader)
        before = row(db)
        with db.transaction() as lock:
            acquire_graph_mutation_lock(lock, shared=False)
            result, adapter = verified(target, leader)
            with pytest.raises(RebuildControlRejected, match="drained"):
                control.publish(leader, lock, ticket, result, adapter)
        assert row(db) == before
        assert control.fail(leader, ticket)


def test_stale_ticket_cannot_publish_or_fail_new_rebuild(store, target):
    with graph_leadership(store) as leader:
        control = RebuildControl(store)
        first = control.begin(leader)
        assert control.fail(leader, first)
        second = control.begin(leader)
        before = row(store)
        with store.transaction() as lock:
            acquire_graph_mutation_lock(lock, shared=False)
            result, adapter = verified(target, leader)
            with pytest.raises(RebuildControlRejected, match="stale"):
                control.publish(leader, lock, first, result, adapter)
        assert not control.fail(leader, first)
        assert row(store) == before
        assert control.fail(leader, second)


@pytest.mark.parametrize("damage", ["unvalidated", "wrong_hash", "bad_time"])
def test_dto_does_not_replace_neo4j_validation_proof(store, target, damage):
    with graph_leadership(store) as leader:
        control = RebuildControl(store)
        ticket = control.begin(leader)
        before = row(store)
        with store.transaction() as lock:
            acquire_graph_mutation_lock(lock, shared=False)
            result, adapter = verified(target, leader)
            driver, generation, _ = target
            with driver.session() as session:
                queries = {
                    "unvalidated": "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated=false",
                    "wrong_hash": "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.snapshot_hash='bad'",
                    "bad_time": "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated_at='not-a-time'",
                }
                session.run(queries[damage], generation=generation).consume()
            with pytest.raises((GraphGenerationUnavailable, ProjectionIntegrityError)):
                control.publish(leader, lock, ticket, result, adapter)
        assert row(store) == before
        assert control.fail(leader, ticket)


@pytest.mark.parametrize("shared", [None, True])
def test_publication_requires_existing_exclusive_lock(store, target, shared):
    with graph_leadership(store) as leader:
        control = RebuildControl(store)
        ticket = control.begin(leader)
        result, adapter = verified(target, leader)
        with store.transaction() as lock:
            if shared is not None:
                acquire_graph_mutation_lock(lock, shared=shared)
            with pytest.raises(ValueError, match="exclusive"):
                control.publish(leader, lock, ticket, result, adapter)
        assert control.fail(leader, ticket)


def test_leadership_loss_leaves_flag_for_recovery(store):
    with graph_leadership(store) as leader:
        control = RebuildControl(store)
        control.begin(leader)
        before = row(store)
        leader._connection.close()
        with pytest.raises(GraphLeadershipLost):
            control.begin(leader)
        assert row(store) == before
        assert ProjectionState(store).observe().status == "REBUILDING"


def test_applied_events_do_not_block_publication(queued, target):
    db, _, _ = queued
    with db.transaction() as connection:
        connection.execute("UPDATE graph_outbox SET status='APPLIED'")
    with graph_leadership(db) as leader:
        control = RebuildControl(db)
        ticket = control.begin(leader)
        with db.transaction() as lock:
            acquire_graph_mutation_lock(lock, shared=False)
            result, adapter = verified(target, leader)
            control.publish(leader, lock, ticket, result, adapter)
    assert ProjectionState(db).observe().status == "CURRENT"


def test_pointer_write_failure_does_not_clear_rebuild_flag(store, target):
    import psycopg

    with store.transaction() as connection:
        connection.execute(
            "CREATE OR REPLACE FUNCTION fail_rebuild_pointer() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.active_generation IS DISTINCT FROM OLD.active_generation THEN RAISE EXCEPTION 'injected pointer failure'; END IF; RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER fail_pointer BEFORE UPDATE ON graph_projection_control FOR EACH ROW EXECUTE FUNCTION fail_rebuild_pointer()"
        )
    try:
        with graph_leadership(store) as leader:
            control = RebuildControl(store)
            ticket = control.begin(leader)
            before = row(store)
            with store.transaction() as lock:
                acquire_graph_mutation_lock(lock, shared=False)
                result, adapter = verified(target, leader)
                with pytest.raises(psycopg.Error):
                    control.publish(leader, lock, ticket, result, adapter)
            assert row(store) == before
            assert control.fail(leader, ticket)
    finally:
        with store.transaction() as connection:
            connection.execute("DROP TRIGGER IF EXISTS fail_pointer ON graph_projection_control")
            connection.execute("DROP FUNCTION IF EXISTS fail_rebuild_pointer()")


def test_changed_previous_generation_fences_old_operation(store, target):
    with graph_leadership(store) as leader:
        control = RebuildControl(store)
        ticket = control.begin(leader)
        with store.transaction() as connection:
            connection.execute(
                "UPDATE graph_projection_control SET active_generation=%s", (uuid4(),)
            )
        before = row(store)
        with store.transaction() as lock:
            acquire_graph_mutation_lock(lock, shared=False)
            result, adapter = verified(target, leader)
            with pytest.raises(RebuildControlRejected, match="stale"):
                control.publish(leader, lock, ticket, result, adapter)
        assert not control.fail(leader, ticket)
        assert row(store) == before
