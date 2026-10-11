"""Recovery changes ownership, never Graph publication or Outbox outcomes."""

from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import psycopg
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


@pytest.mark.parametrize("status", ["PENDING", "PROCESSING", "RETRYABLE", "APPLIED", "DEAD"])
def test_new_leader_adopts_null_pointer_and_fences_old_ticket_without_changing_events(
    queued, status
):
    db, _, _ = queued
    control = RebuildControl(db)
    with db.transaction() as c:
        c.execute("UPDATE graph_outbox SET status=%s", (status,))
        c.execute("UPDATE graph_projection_control SET fatal_error='RESTORE_REQUIRED'")
    with graph_leadership(db) as old_leader:
        old = control.begin(old_leader)
        old_leader._connection.close()
    before = row(db)
    before_events = ordered(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        resumed = control.resume(leader, lock, old)
        assert resumed.rebuild_id != old.rebuild_id and resumed.previous_generation is None
        saved = row(db)
        assert saved["rebuild_id"] == resumed.rebuild_id
        assert saved["rebuild_flag"] and saved["fatal_error"] == before["fatal_error"]
        assert saved["active_generation"] is None
        assert ordered(db) == before_events
        assert ProjectionState(db).observe().status == "REBUILDING"
        assert not control.fail(leader, old)
        with pytest.raises(RebuildControlRejected):
            control.heartbeat(leader, lock, old)
        with pytest.raises(RebuildControlRejected):
            control.resume(leader, lock, old)
        with pytest.raises(RebuildControlRejected):
            RebuildQueue(db).claim(leader, lock, old)
        assert control.fail(leader, resumed)


def test_recovery_requires_actual_validation_of_existing_pointer(queued, target):
    db, _, _ = queued
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        result, adapter = verified(target, leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_projection_control SET active_generation=%s,fatal_error='OLD_ERROR'",
                (UUID(result.generation),),
            )
        old = control.begin(leader)
        before = row(db)
        with pytest.raises(RebuildControlRejected):
            control.resume(leader, lock, old)
        with pytest.raises(RebuildControlRejected):
            control.resume(
                leader,
                lock,
                old,
                verified=replace(result, generation=str(uuid4())),
                adapter=adapter,
            )
        assert row(db) == before
        resumed = control.resume(leader, lock, old, verified=result, adapter=adapter)
        assert resumed.previous_generation == old.previous_generation
        assert row(db)["fatal_error"] == "OLD_ERROR" and row(db)["rebuild_flag"]
        assert not control.fail(leader, old)
        assert control.fail(leader, resumed)


def test_unvalidated_marker_never_changes_recovery_owner(queued, target):
    db, _, _ = queued
    driver, _, adapter = target
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        result, _ = verified(target, leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_projection_control SET active_generation=%s",
                (UUID(result.generation),),
            )
        old = control.begin(leader)
        with driver.session() as session:
            session.run(
                "MATCH (g:LineScopeGeneration {generation:$g}) SET g.validated=false",
                g=result.generation,
            ).consume()
        before = row(db)
        with pytest.raises(GraphGenerationUnavailable):
            control.resume(leader, lock, old, verified=result, adapter=adapter)
        assert row(db) == before


def test_lock_lost_during_generation_verification_never_changes_owner(queued, target, monkeypatch):
    db, _, _ = queued
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        result, adapter = verified(target, leader)
        with db.transaction() as c:
            c.execute(
                "UPDATE graph_projection_control SET active_generation=%s",
                (UUID(result.generation),),
            )
        old = control.begin(leader)
        before = row(db)
        require_verified = adapter.require_verified

        def close(**kwargs):
            require_verified(**kwargs)
            lock.close()

        monkeypatch.setattr(adapter, "require_verified", close)
        with pytest.raises((ValueError, psycopg.Error)):
            control.resume(leader, lock, old, verified=result, adapter=adapter)
        assert row(db) == before


@pytest.mark.parametrize("damage", ["id", "pointer", "flag"])
def test_recovery_rejects_changed_publication_or_ownership(queued, damage):
    db, _, _ = queued
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        old = control.begin(leader)
        if damage == "id":
            old = replace(old, rebuild_id=uuid4())
        elif damage == "pointer":
            with db.transaction() as c:
                c.execute("UPDATE graph_projection_control SET active_generation=%s", (uuid4(),))
        else:
            assert control.fail(leader, old)
        before = row(db)
        with pytest.raises(RebuildControlRejected):
            control.resume(leader, lock, old)
        assert row(db) == before


@pytest.mark.parametrize("shared", [True, None])
def test_recovery_requires_exclusive_mutation_lock(queued, shared):
    db, _, _ = queued
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        old = control.begin(leader)
        if shared is not None:
            acquire_graph_mutation_lock(lock, shared=shared)
        before = row(db)
        with pytest.raises(ValueError):
            control.resume(leader, lock, old)
        assert row(db) == before


def test_recovery_write_failure_rolls_back_owner_change(queued):
    db, _, _ = queued
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        old = control.begin(leader)
        with db.transaction() as c:
            c.execute(
                "CREATE FUNCTION reject_recovery() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN IF NEW.rebuild_id<>OLD.rebuild_id THEN RAISE EXCEPTION 'fault'; "
                "END IF; RETURN NEW; END $$"
            )
            c.execute(
                "CREATE TRIGGER reject_recovery BEFORE UPDATE ON graph_projection_control "
                "FOR EACH ROW EXECUTE FUNCTION reject_recovery()"
            )
        before = row(db)
        with pytest.raises(psycopg.Error):
            control.resume(leader, lock, old)
        assert row(db) == before


def test_postcommit_leader_loss_keeps_new_owner_unknown(queued, monkeypatch):
    db, _, _ = queued
    control = RebuildControl(db)
    transaction = db.transaction
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        old = control.begin(leader)

        @contextmanager
        def commit_and_close():
            with transaction() as c:
                yield c
            leader._connection.close()

        monkeypatch.setattr(db, "transaction", commit_and_close)
        with pytest.raises(GraphLeadershipLost):
            control.resume(leader, lock, old)
        monkeypatch.undo()
        assert row(db)["rebuild_id"] != old.rebuild_id
        assert row(db)["rebuild_flag"] and row(db)["active_generation"] is None


def test_observation_preserves_abandoned_control_and_can_supply_resume_ticket(queued):
    db, _, _ = queued
    control = RebuildControl(db)
    with graph_leadership(db) as old_leader:
        old = control.begin(old_leader)
    before, events = row(db), ordered(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        observation = control.observe(leader, lock)
        assert observation.rebuild_flag
        assert observation.recovery_ticket() == old
        assert observation.fatal_error == before["fatal_error"]
        assert row(db) == before and ordered(db) == events
        resumed = control.resume(leader, lock, observation.recovery_ticket())
        with pytest.raises(RebuildControlRejected):
            control.resume(leader, lock, observation.recovery_ticket())
        assert control.fail(leader, resumed)


def test_observation_of_completed_control_is_not_recovery_ownership(queued):
    db, _, _ = queued
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        before = row(db)
        observation = control.observe(leader, lock)
        assert not observation.rebuild_flag
        assert observation.active_generation == before["active_generation"]
        with pytest.raises(RebuildControlRejected):
            observation.recovery_ticket()
        assert row(db) == before


@pytest.mark.parametrize("shared", [True, None])
def test_observation_requires_exclusive_mutation_lock(queued, shared):
    db, _, _ = queued
    with graph_leadership(db) as leader, db.transaction() as lock:
        if shared is not None:
            acquire_graph_mutation_lock(lock, shared=shared)
        before = row(db)
        with pytest.raises(ValueError):
            RebuildControl(db).observe(leader, lock)
        assert row(db) == before


def test_observation_rejects_lost_leadership(queued):
    db, _, _ = queued
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        leader._connection.close()
        with pytest.raises(GraphLeadershipLost):
            RebuildControl(db).observe(leader, lock)


def test_observation_checks_lock_again_after_read(queued, monkeypatch):
    import linescope.graph.rebuild_control as module

    db, _, _ = queued
    original = module.observe_rebuild
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)

        def lose_lock(connection):
            result = original(connection)
            lock.close()
            return result

        monkeypatch.setattr(module, "observe_rebuild", lose_lock)
        with pytest.raises(ValueError):
            RebuildControl(db).observe(leader, lock)


def test_observation_reports_pointer_and_error_without_inferring_graph_validity(queued):
    db, _, _ = queued
    generation = uuid4()
    with db.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=%s",
            (generation, "RESTORE_REQUIRED"),
        )
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        before = row(db)
        observation = RebuildControl(db).observe(leader, lock)
        assert observation.active_generation == generation
        assert observation.fatal_error == "RESTORE_REQUIRED"
        assert row(db) == before
        with pytest.raises(RebuildControlRejected):
            observation.recovery_ticket()


def test_absent_control_cannot_be_observed_as_recoverable(queued, monkeypatch):
    import linescope.graph.rebuild_control as module

    db, _, _ = queued
    monkeypatch.setattr(module, "observe_rebuild", lambda connection: None)
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        with pytest.raises(RebuildControlRejected, match="absent"):
            RebuildControl(db).observe(leader, lock)
