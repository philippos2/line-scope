"""Restore staging is a fenced drain target, never a CURRENT publication."""

from uuid import UUID, uuid4

import pytest

from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_projection_queue import ordered
from graph.test_projection_queue import queued as queued
from graph.test_rebuild_control import row, verified
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.neo4j_projection import GraphGenerationUnavailable
from linescope.graph.projection_state import ProjectionState
from linescope.graph.rebuild_control import RebuildControl, RebuildControlRejected
from linescope.graph.rebuild_queue import RebuildQueue


@pytest.fixture
def restore(queued):
    db, _, _ = queued
    with db.transaction() as connection:
        connection.execute(
            "UPDATE graph_projection_control SET active_generation=NULL,fatal_error='RESTORE_REQUIRED'"
        )
    return db


def test_staging_preserves_rebuilding_error_and_events_and_replaces_ticket(restore, target):
    db = restore
    before_events = ordered(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        control = RebuildControl(db)
        original = control.begin(leader)
        result, adapter = verified(target, leader)
        ticket = control.stage_restore(leader, lock, original, result, adapter)
        saved = row(db)
        assert ticket.rebuild_id == original.rebuild_id
        assert ticket.previous_generation == UUID(result.generation)
        assert saved["active_generation"] == ticket.previous_generation
        assert saved["rebuild_flag"] and saved["fatal_error"] == "RESTORE_REQUIRED"
        assert ProjectionState(db).observe().status == "REBUILDING"
        assert ordered(db) == before_events
        assert not control.fail(leader, original)
        with pytest.raises(RebuildControlRejected):
            RebuildQueue(db).claim(leader, lock, original)
        assert RebuildQueue(db).claim(leader, lock, ticket).status == "CLAIMED"
        assert control.fail(leader, ticket)
    assert row(db)["active_generation"] == ticket.previous_generation
    assert ProjectionState(db).observe().status == "ERROR"


@pytest.mark.parametrize("gate", ["dead", "applied", "stale", "flag", "pointer"])
def test_staging_rejects_invalid_control_or_queue_without_mutation(restore, target, gate):
    db = restore
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        control = RebuildControl(db)
        ticket = control.begin(leader)
        result, adapter = verified(target, leader)
        with db.transaction() as connection:
            if gate == "dead":
                connection.execute("UPDATE graph_outbox SET status=%s", ("DEAD",))
            elif gate == "applied":
                connection.execute("UPDATE graph_outbox SET status=%s", ("APPLIED",))
            elif gate == "stale":
                connection.execute("UPDATE graph_projection_control SET rebuild_id=%s", (uuid4(),))
            elif gate == "flag":
                connection.execute("UPDATE graph_projection_control SET rebuild_flag=false")
            else:
                connection.execute(
                    "UPDATE graph_projection_control SET active_generation=%s", (uuid4(),)
                )
        before, events = row(db), ordered(db)
        with pytest.raises(RebuildControlRejected):
            control.stage_restore(leader, lock, ticket, result, adapter)
        assert row(db) == before and ordered(db) == events


@pytest.mark.parametrize("shared", [None, True])
def test_staging_requires_exclusive_lock(restore, target, shared):
    with graph_leadership(restore) as leader, restore.transaction() as lock:
        control = RebuildControl(restore)
        ticket = control.begin(leader)
        result, adapter = verified(target, leader)
        if shared is not None:
            acquire_graph_mutation_lock(lock, shared=shared)
        before = row(restore)
        with pytest.raises(ValueError, match="exclusive"):
            control.stage_restore(leader, lock, ticket, result, adapter)
        assert row(restore) == before


def test_staging_requires_actual_neo4j_validation(restore, target):
    with graph_leadership(restore) as leader, restore.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        control = RebuildControl(restore)
        ticket = control.begin(leader)
        result, adapter = verified(target, leader)
        driver, generation, _ = target
        with driver.session() as session:
            session.run(
                "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated=false",
                generation=generation,
            ).consume()
        before = row(restore)
        with pytest.raises(GraphGenerationUnavailable):
            control.stage_restore(leader, lock, ticket, result, adapter)
        assert row(restore) == before


def test_lost_lock_during_verification_prevents_staging(restore, target, monkeypatch):
    with graph_leadership(restore) as leader, restore.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        control = RebuildControl(restore)
        ticket = control.begin(leader)
        result, adapter = verified(target, leader)
        require = adapter.require_verified

        def close_lock(**kwargs):
            require(**kwargs)
            lock.close()

        monkeypatch.setattr(adapter, "require_verified", close_lock)
        before = row(restore)
        with pytest.raises(ValueError, match="transaction"):
            control.stage_restore(leader, lock, ticket, result, adapter)
        assert row(restore) == before


def test_postcommit_leader_loss_keeps_staged_pointer_unknown(restore, target, monkeypatch):
    import linescope.graph.rebuild_control as module

    original = module.stage_restore_generation
    with graph_leadership(restore) as leader, restore.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        control = RebuildControl(restore)
        ticket = control.begin(leader)
        result, adapter = verified(target, leader)
        real_require = leader.require
        calls = [0]

        def require():
            calls[0] += 1
            if calls[0] == 2:
                leader._connection.close()
            real_require()

        def stage(*args):
            changed = original(*args)
            monkeypatch.setattr(leader, "require", require)
            return changed

        monkeypatch.setattr(module, "stage_restore_generation", stage)
        with pytest.raises(GraphLeadershipLost):
            control.stage_restore(leader, lock, ticket, result, adapter)
        saved = row(restore)
        assert saved["active_generation"] == UUID(result.generation)
        assert saved["rebuild_flag"] and saved["fatal_error"] == "RESTORE_REQUIRED"
        assert all(event["status"] == "PENDING" for event in ordered(restore))


def test_pointer_write_failure_rolls_back_staging(restore, target):
    import psycopg

    with restore.transaction() as connection:
        connection.execute(
            "CREATE FUNCTION reject_restore_pointer() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF NEW.active_generation IS NOT NULL THEN RAISE EXCEPTION 'reject'; "
            "END IF; RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_restore_pointer BEFORE UPDATE ON graph_projection_control "
            "FOR EACH ROW EXECUTE FUNCTION reject_restore_pointer()"
        )
    with graph_leadership(restore) as leader, restore.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        control = RebuildControl(restore)
        ticket = control.begin(leader)
        result, adapter = verified(target, leader)
        before, events = row(restore), ordered(restore)
        with pytest.raises(psycopg.errors.RaiseException):
            control.stage_restore(leader, lock, ticket, result, adapter)
        assert row(restore) == before and ordered(restore) == events
        assert control.fail(leader, ticket)
