"""Real PG fences and real Neo4j replay; no generated-SQL assertions."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from graph.test_neo4j_projection import graph as graph
from graph.test_neo4j_projection import graph_driver as graph_driver
from graph.test_neo4j_projection import seed_endpoints
from graph.test_outbox import events
from graph.test_projection_application import RecordingAdapter, stored
from graph.test_projection_queue import queued as queued
from graph.test_rebuild_queue import prepare
from graph.test_rebuild_queue import world as world
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.rebuild_application import RebuildApplication
from linescope.persistence.database import Database


def claim(db, leader, lock):
    ticket, queue = prepare(db, leader, lock)
    return ticket, queue.claim(leader, lock, ticket).event


def test_saved_payload_commit_order_and_caller_lock(world):
    contender = Database(replace(world.settings, lock_ms=50, statement_ms=1000))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)

        def check(arguments):
            assert stored(world, event)["status"] == "PROCESSING"
            assert arguments["payload"] == event["payload"]
            assert arguments["generation"] == ticket.previous_generation
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with contender.transaction() as c:
                    acquire_graph_mutation_lock(c, shared=True)
            with contender.transaction() as c:
                c.execute("SELECT outbox_id FROM graph_outbox FOR UPDATE")
                c.execute("SELECT control_id FROM graph_projection_control FOR UPDATE")

        adapter = RecordingAdapter(check)
        service = RebuildApplication(world)
        assert service.apply(leader, lock, ticket, {**event, "payload": {}}, adapter)
        row = stored(world, event)
        assert row["status"] == "APPLIED" and row["processed_at"] is not None
        assert row["attempt_count"] == 1
        assert row["processing_started_at"] is row["next_attempt_at"] is row["last_error"] is None
        assert lock.info.transaction_status == TransactionStatus.INTRANS
        assert not service.apply(leader, lock, ticket, event, adapter)
        assert len(adapter.calls) == 1


@pytest.mark.parametrize(
    "damage",
    ["id", "generation", "flag", "expired", "attempt", "start", "dead", "terminal", "missing"],
)
def test_fences_before_io(world, damage):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        with world.transaction() as c:
            if damage == "id":
                ticket = replace(ticket, rebuild_id=uuid4())
            elif damage == "generation":
                ticket = replace(ticket, previous_generation=uuid4())
            elif damage == "flag":
                c.execute("UPDATE graph_projection_control SET rebuild_flag=false")
            elif damage == "missing":
                c.execute("UPDATE graph_projection_control SET active_generation=NULL")
            elif damage == "expired":
                c.execute(
                    "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                    (event["outbox_id"],),
                )
            elif damage == "attempt":
                event = {**event, "attempt_count": event["attempt_count"] + 1}
            elif damage == "start":
                event = {
                    **event,
                    "processing_started_at": event["processing_started_at"] - timedelta(seconds=1),
                }
            elif damage == "dead":
                c.execute(
                    "UPDATE graph_outbox SET status='DEAD' WHERE outbox_id<>%s",
                    (event["outbox_id"],),
                )
            else:
                c.execute(
                    "UPDATE graph_outbox SET status='APPLIED' WHERE outbox_id=%s",
                    (event["outbox_id"],),
                )
        if damage == "expired":
            event = {
                **event,
                "processing_started_at": stored(world, event)["processing_started_at"],
            }
        before = events(world)
        adapter = RecordingAdapter()
        assert not RebuildApplication(world).apply(leader, lock, ticket, event, adapter)
        assert not adapter.calls and events(world) == before


@pytest.mark.parametrize("damage", ["id", "generation", "flag", "dead", "attempt", "expired"])
def test_fences_rechecked_after_external_commit(world, damage):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)

        def change(arguments):
            with world.transaction() as c:
                if damage == "id":
                    c.execute("UPDATE graph_projection_control SET rebuild_id=%s", (uuid4(),))
                elif damage == "generation":
                    c.execute(
                        "UPDATE graph_projection_control SET active_generation=%s", (uuid4(),)
                    )
                elif damage == "flag":
                    c.execute("UPDATE graph_projection_control SET rebuild_flag=false")
                elif damage == "dead":
                    c.execute(
                        "UPDATE graph_outbox SET status='DEAD' WHERE outbox_id<>%s",
                        (event["outbox_id"],),
                    )
                elif damage == "attempt":
                    c.execute(
                        "UPDATE graph_outbox SET attempt_count=attempt_count+1 WHERE outbox_id=%s",
                        (event["outbox_id"],),
                    )
                else:
                    c.execute(
                        "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                        (event["outbox_id"],),
                    )

        assert not RebuildApplication(world).apply(
            leader, lock, ticket, event, RecordingAdapter(change)
        )
        assert stored(world, event)["status"] == "PROCESSING"
        assert stored(world, event)["processed_at"] is None


@pytest.mark.parametrize("shared", [None, True])
def test_requires_caller_exclusive_lock(world, shared):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
    with graph_leadership(world) as leader, world.transaction() as lock:
        if shared is not None:
            acquire_graph_mutation_lock(lock, shared=shared)
        with pytest.raises(ValueError, match="exclusive"):
            RebuildApplication(world).apply(leader, lock, ticket, event, RecordingAdapter())
    assert stored(world, event)["status"] == "PROCESSING"


def test_adapter_failure_leaves_replayable_claim_and_caller_lock(world):
    def fail(arguments):
        raise RuntimeError("external failure")

    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        with pytest.raises(RuntimeError):
            RebuildApplication(world).apply(leader, lock, ticket, event, RecordingAdapter(fail))
        assert stored(world, event)["status"] == "PROCESSING"
        assert lock.info.transaction_status == TransactionStatus.INTRANS


def test_leader_or_lock_loss_prevents_ack(world):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        with pytest.raises(GraphLeadershipLost):
            RebuildApplication(world).apply(
                leader, lock, ticket, event, RecordingAdapter(lambda _: leader._connection.close())
            )
        assert stored(world, event)["status"] == "PROCESSING"


def test_lock_loss_prevents_ack(world):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        with pytest.raises((ValueError, psycopg.Error)):
            RebuildApplication(world).apply(
                leader, lock, ticket, event, RecordingAdapter(lambda _: lock.close())
            )
        assert stored(world, event)["status"] == "PROCESSING"


def test_real_neo4j_commit_ack_failure_and_idempotent_replay(world, graph):
    driver, generation, adapter = graph
    with world.transaction() as c:
        c.execute("UPDATE graph_projection_control SET active_generation=%s", (UUID(generation),))
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        seed_endpoints(graph, event["payload"])
        with world.transaction() as c:
            c.execute(
                "CREATE FUNCTION reject_rebuild_ack() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'ack fault'; END $$"
            )
            c.execute(
                "CREATE TRIGGER reject_rebuild_ack BEFORE UPDATE ON graph_outbox FOR EACH ROW EXECUTE FUNCTION reject_rebuild_ack()"
            )
        service = RebuildApplication(world)
        with pytest.raises(psycopg.Error):
            service.apply(leader, lock, ticket, event, adapter)
        assert stored(world, event)["status"] == "PROCESSING"
        with driver.session() as session:
            result = session.run(
                "MATCH (m:LineScopeProjectionMarker {generation:$g}) RETURN count(m) AS n",
                g=generation,
            ).single()
            assert result["n"] == 1
        with world.transaction() as c:
            c.execute("DROP TRIGGER reject_rebuild_ack ON graph_outbox")
        assert service.apply(leader, lock, ticket, event, adapter)
        assert stored(world, event)["status"] == "APPLIED"
        with driver.session() as session:
            assert (
                session.run(
                    "MATCH (m:LineScopeProjectionMarker {generation:$g}) RETURN count(m) AS n",
                    g=generation,
                ).single()["n"]
                == 1
            )


def test_ack_commit_holds_caller_lock(world, monkeypatch):
    from linescope.graph import rebuild_application as module

    original = module.acknowledge_rebuild_graph_application
    contender = Database(replace(world.settings, lock_ms=50, statement_ms=1000))
    observed = []

    def acknowledge(connection, event, lease_seconds, generation, ticket):
        changed = original(connection, event, lease_seconds, generation, ticket)
        assert stored(world, event)["status"] == "PROCESSING"
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with contender.transaction() as c:
                acquire_graph_mutation_lock(c, shared=True)
        observed.append(changed)
        return changed

    monkeypatch.setattr(module, "acknowledge_rebuild_graph_application", acknowledge)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        assert RebuildApplication(world).apply(leader, lock, ticket, event, RecordingAdapter())
    assert observed == [True] and stored(world, event)["status"] == "APPLIED"


def test_leader_loss_before_ack_commit_rolls_back(world, monkeypatch):
    from linescope.graph import rebuild_application as module

    original = module.acknowledge_rebuild_graph_application

    def acknowledge(connection, event, lease_seconds, generation, ticket):
        changed = original(connection, event, lease_seconds, generation, ticket)
        leader._connection.close()
        return changed

    monkeypatch.setattr(module, "acknowledge_rebuild_graph_application", acknowledge)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        with pytest.raises(GraphLeadershipLost):
            RebuildApplication(world).apply(leader, lock, ticket, event, RecordingAdapter())
    assert stored(world, event)["status"] == "PROCESSING"
    assert stored(world, event)["processed_at"] is None


@pytest.mark.parametrize("damage", ["schema", "aggregate"])
def test_saved_payload_validated_before_io(world, damage):
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, event = claim(world, leader, lock)
        with world.transaction() as c:
            if damage == "schema":
                c.execute(
                    "UPDATE graph_outbox SET payload=jsonb_set(payload,'{schema_version}','99') WHERE outbox_id=%s",
                    (event["outbox_id"],),
                )
            else:
                c.execute(
                    "UPDATE graph_outbox SET aggregate_id=%s WHERE outbox_id=%s",
                    (uuid4(), event["outbox_id"]),
                )
        adapter = RecordingAdapter()
        with pytest.raises(ValueError):
            RebuildApplication(world).apply(leader, lock, ticket, event, adapter)
        assert not adapter.calls and stored(world, event)["status"] == "PROCESSING"
