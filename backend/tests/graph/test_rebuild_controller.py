"""Real PG/Neo4j initial and normal Rebuild lifecycle, plus failure boundaries."""

import io
import json
from dataclasses import replace
from uuid import UUID, uuid4

import psycopg
import pytest

from graph.test_neo4j_projection import graph as graph
from graph.test_neo4j_projection import graph_driver as graph_driver
from graph.test_neo4j_projection import seed_endpoints
from graph.test_outbox import events
from graph.test_projection_queue import queued as queued
from graph.test_rebuild_control import row
from graph.test_rebuild_drain import Clock
from graph.test_rebuild_queue import world as world
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.neo4j_generation import Neo4jGeneration
from linescope.graph.neo4j_projection import Neo4jProjection, ProjectionIntegrityError
from linescope.graph.projection_state import ProjectionState
from linescope.graph.rebuild_control import RebuildControl, RebuildControlRejected
from linescope.graph.rebuild_controller import RebuildController
from linescope.graph.rebuild_drain import RebuildDrainStopped, RebuildDrainTimeout
from linescope.logging import EventLogger
from linescope.persistence.database import Database

SECRET = "private-password-token-payload"


@pytest.fixture
def empty(db):
    db.migrate()
    return db


@pytest.fixture
def adapters(graph_driver):
    before = set()
    with graph_driver.session() as session:
        before = {
            row["g"]
            for row in session.run("MATCH (g:LineScopeGeneration) RETURN g.generation AS g")
        }
    yield Neo4jProjection(graph_driver), Neo4jGeneration(graph_driver)
    with graph_driver.session() as session:
        after = {
            row["g"]
            for row in session.run("MATCH (g:LineScopeGeneration) RETURN g.generation AS g")
        }
        for generation in after - before:
            session.run("MATCH (n {generation:$g}) DETACH DELETE n", g=generation).consume()


def controller(db, adapters, **kwargs):
    output = io.StringIO()
    service = RebuildController(
        db,
        *adapters,
        logger=EventLogger(stream=output),
        **kwargs,
    )
    return service, output


def logs(output):
    assert SECRET not in output.getvalue()
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_initial_rebuild_publishes_verified_empty_graph_and_logs_completion(empty, adapters):
    service, output = controller(empty, adapters)
    with graph_leadership(empty) as leader:
        result = service.run(leader)
        leader.require()
    control = row(empty)
    assert control["active_generation"] == UUID(result.generation)
    assert not control["rebuild_flag"] and control["fatal_error"] is None
    assert ProjectionState(empty).observe().status == "CURRENT"
    assert result.node_count == result.aggregate_count == 0
    recorded = logs(output)
    assert [entry["event"] for entry in recorded] == ["rebuild.started", "rebuild.completed"]
    assert recorded[0]["request_id"] == recorded[1]["request_id"]
    assert recorded[1]["rebuild_id"] == str(control["rebuild_id"])
    assert recorded[1]["graph_generation"] == result.generation
    assert recorded[1]["event_count"] == 0
    with empty.transaction() as c:
        acquire_graph_mutation_lock(c, shared=True)


def test_normal_rebuild_drains_before_snapshot_and_retains_old_graph(world, graph, adapters):
    driver, generation, _ = graph
    with world.transaction() as c:
        c.execute("UPDATE graph_projection_control SET active_generation=%s", (UUID(generation),))
    for event in events(world):
        seed_endpoints(graph, event["payload"])
    service, output = controller(world, adapters)
    with graph_leadership(world) as leader:
        result = service.run(leader)
    assert result.generation != generation and row(world)["active_generation"] == UUID(
        result.generation
    )
    assert all(event["status"] == "APPLIED" for event in events(world))
    assert ProjectionState(world).observe().status == "CURRENT"
    with driver.session() as session:
        assert (
            session.run(
                "MATCH (g:LineScopeGeneration {generation:$g,validated:true}) RETURN count(g) AS n",
                g=generation,
            ).single()["n"]
            == 1
        )
    recorded = logs(output)
    assert recorded[-1]["event"] == "rebuild.completed" and recorded[-1]["event_count"] == 3
    assert all(entry["rebuild_id"] == recorded[0]["rebuild_id"] for entry in recorded)


def test_dead_aborts_without_build_or_pointer_change(world, adapters):
    previous = row(world)["active_generation"]
    with world.transaction() as c:
        c.execute("UPDATE graph_outbox SET status='DEAD'")
    service, output = controller(world, adapters)
    with graph_leadership(world) as leader, pytest.raises(RebuildDrainStopped):
        service.run(leader)
    control = row(world)
    assert control["active_generation"] == previous
    assert control["fatal_error"] == "REBUILD_FAILED" and not control["rebuild_flag"]
    assert logs(output)[-1]["outcome"] == "failure"
    with world.transaction() as c:
        acquire_graph_mutation_lock(c, shared=True)


def test_shared_deadline_wait_timeout_saves_failure(world, adapters):
    clock = Clock()
    with world.transaction() as c:
        c.execute(
            "UPDATE graph_outbox SET status='RETRYABLE',next_attempt_at=statement_timestamp()+interval '1 hour'"
        )
    service, output = controller(world, adapters, timeout_ms=2500, clock=clock, wait=clock.wait)
    previous = row(world)["active_generation"]
    with graph_leadership(world) as leader, pytest.raises(RebuildDrainTimeout):
        service.run(leader)
    assert clock.waits == [1, 1, 0.5]
    assert row(world)["active_generation"] == previous
    assert row(world)["fatal_error"] == "REBUILD_FAILED" and not row(world)["rebuild_flag"]
    assert logs(output)[-1]["outcome"] == "failure"


@pytest.mark.parametrize("fault", ["build", "verify"])
def test_graph_failure_never_publishes_and_keeps_fixed_diagnosis(
    empty, adapters, monkeypatch, fault
):
    def fail(**kwargs):
        raise ProjectionIntegrityError(SECRET)

    monkeypatch.setattr(adapters[1], "build" if fault == "build" else "require_verified", fail)
    service, output = controller(empty, adapters)
    with graph_leadership(empty) as leader, pytest.raises(ProjectionIntegrityError):
        service.run(leader)
    assert row(empty)["active_generation"] is None
    assert row(empty)["fatal_error"] == "REBUILD_FAILED" and not row(empty)["rebuild_flag"]
    assert logs(output)[-1]["event"] == "rebuild.failed"


def test_leader_loss_during_build_leaves_flag_for_recovery(empty, adapters, monkeypatch):
    with graph_leadership(empty) as leader:

        def fail(**kwargs):
            leader._connection.close()
            raise GraphLeadershipLost(SECRET)

        monkeypatch.setattr(adapters[1], "build", fail)
        service, output = controller(empty, adapters)
        with pytest.raises(GraphLeadershipLost):
            service.run(leader)
    assert row(empty)["rebuild_flag"] and row(empty)["active_generation"] is None
    assert logs(output)[-1]["outcome"] == "unknown"


def test_failure_cleanup_storage_fault_remains_unknown(empty, adapters, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(adapters[1], "build", fail)
    with empty.transaction() as c:
        c.execute(
            "CREATE FUNCTION reject_rebuild_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.fatal_error='REBUILD_FAILED' THEN RAISE EXCEPTION 'private-password-token-payload'; END IF; RETURN NEW; END $$"
        )
        c.execute(
            "CREATE TRIGGER reject_rebuild_cleanup BEFORE UPDATE ON graph_projection_control FOR EACH ROW EXECUTE FUNCTION reject_rebuild_cleanup()"
        )
    service, output = controller(empty, adapters)
    with graph_leadership(empty) as leader, pytest.raises(RuntimeError):
        service.run(leader)
    assert row(empty)["rebuild_flag"]
    assert logs(output)[-1]["outcome"] == "unknown"


def test_mutation_lock_timeout_cleans_flag(empty, adapters):
    contender = Database(replace(empty.settings, lock_ms=50, statement_ms=1000))
    service, output = controller(contender, adapters)
    with empty.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=True)
        with graph_leadership(contender) as leader, pytest.raises(psycopg.errors.LockNotAvailable):
            service.run(leader)
    assert not row(empty)["rebuild_flag"] and row(empty)["fatal_error"] == "REBUILD_FAILED"
    assert logs(output)[-1]["outcome"] == "failure"


def test_stale_existing_flag_not_overwritten(empty, adapters):
    with graph_leadership(empty) as leader:
        ticket = RebuildControl(empty).begin(leader)
        service, output = controller(empty, adapters)
        with pytest.raises(RebuildControlRejected):
            service.run(leader)
    assert row(empty)["rebuild_flag"] and row(empty)["rebuild_id"] == ticket.rebuild_id
    assert [entry["event"] for entry in logs(output)] == ["rebuild.failed"]


def test_heartbeat_fenced_and_does_not_clear_fatal(empty):
    with graph_leadership(empty) as leader, empty.transaction() as lock:
        control = RebuildControl(empty)
        ticket = control.begin(leader)
        acquire_graph_mutation_lock(lock, shared=False)
        before = row(empty)
        control.heartbeat(leader, lock, ticket)
        after = row(empty)
        assert after["updated_at"] >= before["updated_at"]
        assert after["fatal_error"] == before["fatal_error"]
        with pytest.raises(RebuildControlRejected):
            control.heartbeat(leader, lock, replace(ticket, rebuild_id=uuid4()))
        assert row(empty) == after


@pytest.mark.parametrize("timeout", [True, 0, -1, 0.5])
def test_invalid_timeout_rejected(empty, adapters, timeout):
    with pytest.raises(ValueError):
        RebuildController(empty, *adapters, timeout_ms=timeout)


def test_deadline_after_build_never_publishes(empty, adapters, monkeypatch):
    clock = Clock()
    original = adapters[1].build

    def build(**kwargs):
        verified = original(**kwargs)
        clock.now = 160
        return verified

    monkeypatch.setattr(adapters[1], "build", build)
    service, output = controller(empty, adapters, clock=clock, wait=clock.wait)
    with graph_leadership(empty) as leader, pytest.raises(RebuildDrainTimeout):
        service.run(leader)
    assert row(empty)["active_generation"] is None
    assert row(empty)["fatal_error"] == "REBUILD_FAILED"
    assert logs(output)[-1]["outcome"] == "failure"


def test_lost_lock_during_verification_never_publishes(empty, adapters, monkeypatch):
    from linescope.graph import rebuild_controller as module

    locks = []
    acquire = module.acquire_graph_mutation_lock
    verify = adapters[1].require_verified

    def record(connection, *, shared):
        acquire(connection, shared=shared)
        locks.append(connection)

    def close(**kwargs):
        verify(**kwargs)
        locks[0].close()

    monkeypatch.setattr(module, "acquire_graph_mutation_lock", record)
    monkeypatch.setattr(adapters[1], "require_verified", close)
    service, output = controller(empty, adapters)
    with graph_leadership(empty) as leader, pytest.raises((ValueError, psycopg.Error)):
        service.run(leader)
    assert row(empty)["active_generation"] is None
    assert row(empty)["fatal_error"] == "REBUILD_FAILED"
    assert logs(output)[-1]["outcome"] == "failure"


def test_postpublication_leader_loss_is_unknown_and_never_reverses_commit(
    empty, adapters, monkeypatch
):
    service, output = controller(empty, adapters)
    publish = service.control.publish
    with graph_leadership(empty) as leader:

        def close(*args):
            publish(*args)
            leader._connection.close()

        monkeypatch.setattr(service.control, "publish", close)
        with pytest.raises(GraphLeadershipLost):
            service.run(leader)
    assert row(empty)["active_generation"] is not None
    assert not row(empty)["rebuild_flag"] and row(empty)["fatal_error"] is None
    assert logs(output)[-1]["outcome"] == "unknown"
    assert all(entry["event"] != "rebuild.completed" for entry in logs(output))
    assert logs(output)[-1]["graph_generation"] == str(row(empty)["active_generation"])
