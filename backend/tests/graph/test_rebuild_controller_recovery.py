"""Explicit recovery reuses verified drainage/publication and preserves old fences."""

from dataclasses import replace
from uuid import UUID

import psycopg
import pytest

from graph.test_neo4j_projection import graph_driver as graph_driver
from graph.test_outbox import events
from graph.test_projection_queue import queued as queued
from graph.test_rebuild_control import row
from graph.test_rebuild_controller import adapters as adapters
from graph.test_rebuild_controller import controller, logs
from graph.test_rebuild_controller import restore as restore
from graph.test_rebuild_drain import Clock
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.neo4j_projection import GraphGenerationUnavailable, ProjectionIntegrityError
from linescope.graph.projection_state import ProjectionState
from linescope.graph.rebuild_control import RebuildControl, RebuildControlRejected
from linescope.graph.rebuild_drain import RebuildDrainStopped, RebuildDrainTimeout
from linescope.graph.rebuild_snapshot import read_rebuild_snapshot
from linescope.persistence.database import Database


def abandon(db, adapters, *, staged=False):
    control = RebuildControl(db)
    with graph_leadership(db) as leader, db.transaction() as lock:
        old = control.begin(leader)
        acquire_graph_mutation_lock(lock, shared=False)
        if staged:
            from uuid import uuid4

            snapshot = read_rebuild_snapshot(lock)
            work = adapters[1].build(generation=uuid4(), snapshot=snapshot, leadership=leader)
            old = control.stage_restore(leader, lock, old, work, adapters[1])
        leader._connection.close()
    return old


@pytest.mark.parametrize("staged", [False, True])
def test_recovery_adopts_abandoned_owner_drains_and_publishes(restore, adapters, staged):
    old = abandon(restore, adapters, staged=staged)
    service, output = controller(restore, adapters)
    with graph_leadership(restore) as leader:
        result = service.recover(leader)
        assert not service.control.fail(leader, old)
    saved = row(restore)
    assert saved["rebuild_id"] != old.rebuild_id
    assert saved["active_generation"] == UUID(result.generation)
    assert saved["active_generation"] != old.previous_generation
    assert not saved["rebuild_flag"] and saved["fatal_error"] is None
    assert all(event["status"] == "APPLIED" for event in events(restore))
    assert ProjectionState(restore).observe().status == "CURRENT"
    entries = logs(output)
    assert [entry["event"] for entry in entries if entry["event"].startswith("rebuild.")] == [
        "rebuild.started",
        "rebuild.completed",
    ]
    assert entries[0]["rebuild_id"] == str(saved["rebuild_id"])
    assert entries[-1]["event_count"] == 3
    with restore.transaction() as c:
        acquire_graph_mutation_lock(c, shared=True)


@pytest.mark.parametrize("damage", ["missing", "unvalidated", "bad_hash"])
def test_recovery_does_not_adopt_or_cleanup_unverified_pointer(restore, adapters, damage):
    old = abandon(restore, adapters, staged=True)
    driver = adapters[1].driver
    query = {
        "missing": "MATCH (n {generation:$g}) DETACH DELETE n",
        "unvalidated": "MATCH (n:LineScopeGeneration {generation:$g}) SET n.validated=false",
        "bad_hash": "MATCH (n:LineScopeGeneration {generation:$g}) SET n.snapshot_hash='bad'",
    }[damage]
    with driver.session() as session:
        session.run(query, g=str(old.previous_generation)).consume()
    before, before_events = row(restore), events(restore)
    service, output = controller(restore, adapters)
    expected = ProjectionIntegrityError if damage == "bad_hash" else GraphGenerationUnavailable
    with graph_leadership(restore) as leader, pytest.raises(expected):
        service.recover(leader)
    assert row(restore) == before and events(restore) == before_events
    assert ProjectionState(restore).observe().status == "REBUILDING"
    assert [entry["event"] for entry in logs(output)] == ["rebuild.failed"]
    assert logs(output)[-1]["outcome"] == "unknown"
    assert logs(output)[-1]["rebuild_id"] == str(old.rebuild_id)
    with restore.transaction() as c:
        acquire_graph_mutation_lock(c, shared=True)


def test_recovery_without_remaining_flag_is_not_a_new_rebuild(restore, adapters):
    before, before_events = row(restore), events(restore)
    service, output = controller(restore, adapters)
    with graph_leadership(restore) as leader, pytest.raises(RebuildControlRejected):
        service.recover(leader)
    assert row(restore) == before and events(restore) == before_events
    assert [entry["event"] for entry in logs(output)] == ["rebuild.failed"]


@pytest.mark.parametrize("staged", [False, True])
def test_recovery_dead_stops_without_retiring_events(restore, adapters, staged):
    old = abandon(restore, adapters, staged=staged)
    with restore.transaction() as c:
        c.execute("UPDATE graph_outbox SET status='DEAD'")
    before_events = events(restore)
    service, output = controller(restore, adapters)
    with graph_leadership(restore) as leader, pytest.raises(RebuildDrainStopped):
        service.recover(leader)
    saved = row(restore)
    assert saved["rebuild_id"] != old.rebuild_id
    assert saved["active_generation"] == old.previous_generation
    assert not saved["rebuild_flag"] and saved["fatal_error"] == "REBUILD_FAILED"
    assert events(restore) == before_events
    assert logs(output)[-1]["outcome"] == "failure"


def test_recovery_failure_after_adoption_uses_new_ticket(restore, adapters, monkeypatch):
    old = abandon(restore, adapters, staged=True)
    before_events = events(restore)
    service, output = controller(restore, adapters)

    def fail(*args, **kwargs):
        raise RuntimeError("private-password-token-payload")

    monkeypatch.setattr(service.drain, "run", fail)
    with graph_leadership(restore) as leader, pytest.raises(RuntimeError):
        service.recover(leader)
    saved = row(restore)
    assert saved["rebuild_id"] != old.rebuild_id
    assert saved["active_generation"] == old.previous_generation
    assert not saved["rebuild_flag"] and saved["fatal_error"] == "REBUILD_FAILED"
    assert events(restore) == before_events
    assert logs(output)[-1]["outcome"] == "failure"
    assert logs(output)[-1]["rebuild_id"] == str(saved["rebuild_id"])


def test_leader_loss_before_adoption_preserves_old_owner(restore, adapters, monkeypatch):
    abandon(restore, adapters, staged=True)
    before, before_events = row(restore), events(restore)
    observe = adapters[1].observe_validation
    service, output = controller(restore, adapters)
    with graph_leadership(restore) as leader:

        def lose(**kwargs):
            proof = observe(**kwargs)
            leader._connection.close()
            return proof

        monkeypatch.setattr(adapters[1], "observe_validation", lose)
        with pytest.raises(GraphLeadershipLost):
            service.recover(leader)
    assert row(restore) == before and events(restore) == before_events
    assert logs(output)[-1]["outcome"] == "unknown"


def test_recovery_observation_consumes_same_deadline_without_adopting(
    restore, adapters, monkeypatch
):
    abandon(restore, adapters, staged=True)
    before, before_events = row(restore), events(restore)
    clock = Clock()
    observe = adapters[1].observe_validation

    def expire(**kwargs):
        proof = observe(**kwargs)
        clock.now = 160
        return proof

    monkeypatch.setattr(adapters[1], "observe_validation", expire)
    service, output = controller(restore, adapters, clock=clock, wait=clock.wait)
    with graph_leadership(restore) as leader, pytest.raises(RebuildDrainTimeout):
        service.recover(leader)
    assert row(restore) == before and events(restore) == before_events
    assert logs(output)[-1]["outcome"] == "unknown"


def test_recovery_lock_timeout_does_not_fail_abandoned_owner(restore, adapters):
    abandon(restore, adapters)
    before, before_events = row(restore), events(restore)
    contender = Database(replace(restore.settings, lock_ms=50, statement_ms=1000))
    service, output = controller(contender, adapters)
    with restore.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=True)
        with graph_leadership(contender) as leader, pytest.raises(psycopg.errors.LockNotAvailable):
            service.recover(leader)
    assert row(restore) == before and events(restore) == before_events
    assert logs(output)[-1]["outcome"] == "unknown"


def test_leader_loss_after_adoption_leaves_new_owner_for_next_recovery(
    restore, adapters, monkeypatch
):
    old = abandon(restore, adapters, staged=True)
    before_events = events(restore)
    service, output = controller(restore, adapters)
    resume = service.control.resume
    with graph_leadership(restore) as leader:

        def lose(*args, **kwargs):
            ticket = resume(*args, **kwargs)
            leader._connection.close()
            return ticket

        monkeypatch.setattr(service.control, "resume", lose)
        with pytest.raises(GraphLeadershipLost):
            service.recover(leader)
    saved = row(restore)
    assert saved["rebuild_id"] != old.rebuild_id
    assert saved["rebuild_flag"] and saved["fatal_error"] == "RESTORE_REQUIRED"
    assert saved["active_generation"] == old.previous_generation
    assert events(restore) == before_events
    assert logs(output)[-1]["outcome"] == "unknown"
    assert logs(output)[-1]["rebuild_id"] == str(saved["rebuild_id"])


def test_recovery_does_not_repeat_already_published_rebuild(restore, adapters):
    service, _ = controller(restore, adapters)
    with graph_leadership(restore) as leader:
        result = service.run(leader)
    before, before_events = row(restore), events(restore)
    recovery, output = controller(restore, adapters)
    with graph_leadership(restore) as leader, pytest.raises(RebuildControlRejected):
        recovery.recover(leader)
    assert before["active_generation"] == UUID(result.generation)
    assert row(restore) == before and events(restore) == before_events
    assert ProjectionState(restore).observe().status == "CURRENT"
    assert [entry["event"] for entry in logs(output)] == ["rebuild.failed"]


def test_unpublished_verified_candidate_is_not_inferred_as_active_generation(restore, adapters):
    from uuid import uuid4

    old = abandon(restore, adapters)
    with graph_leadership(restore) as leader, restore.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        snapshot = read_rebuild_snapshot(lock)
        candidate = adapters[1].build(generation=uuid4(), snapshot=snapshot, leadership=leader)
        leader._connection.close()
    service, _ = controller(restore, adapters)
    with graph_leadership(restore) as leader:
        result = service.recover(leader)
        assert not service.control.fail(leader, old)
        # Recovery retains the verified but unpublished candidate for a later
        # managed cleanup instead of guessing publication or deleting it.
        proof = adapters[1].observe_validation(generation=candidate.generation, leadership=leader)
        assert proof.snapshot_hash == candidate.snapshot_hash
    assert result.generation != candidate.generation
    assert row(restore)["active_generation"] == UUID(result.generation)
    assert ProjectionState(restore).observe().status == "CURRENT"
