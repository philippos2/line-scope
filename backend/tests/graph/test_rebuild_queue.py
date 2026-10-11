from dataclasses import replace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from graph.test_outbox import events
from graph.test_projection_queue import queued as queued
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.neo4j_projection import GraphGenerationUnavailable
from linescope.graph.projection_queue import ProjectionQueue
from linescope.graph.rebuild_control import RebuildControl, RebuildControlRejected
from linescope.graph.rebuild_queue import RebuildQueue


@pytest.fixture
def world(queued):
    db, _, _ = queued
    with db.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET active_generation=%s", (uuid4(),))
    return db


def prepare(db, leader, lock):
    ticket = RebuildControl(db).begin(leader)
    acquire_graph_mutation_lock(lock, shared=False)
    return ticket, RebuildQueue(db)


def test_claim_during_rebuild_ignores_recoverable_fatal_and_preserves_caller_lock(world):
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        assert ProjectionQueue(world).claim(leader) is None
        assert events(world) == before
        result = queue.claim(leader, lock, ticket)
        assert result.status == "CLAIMED"
        assert result.event["attempt_count"] == 1
        assert result.event["processing_started_at"] is not None
        assert lock.info.transaction_status == TransactionStatus.INTRANS
        saved = next(
            item for item in events(world) if item["outbox_id"] == result.event["outbox_id"]
        )
        assert saved["status"] == "PROCESSING"
        assert saved["payload"] == result.event["payload"]


@pytest.mark.parametrize("status", ["PENDING", "RETRYABLE", "PROCESSING"])
def test_dead_anywhere_stops_claim_and_recovery(world, status):
    before = events(world)
    with world.transaction() as connection:
        connection.execute(
            "UPDATE graph_outbox SET status=%s,next_attempt_at=statement_timestamp(),processing_started_at=statement_timestamp()-interval '1 hour'",
            (status,),
        )
        connection.execute(
            "UPDATE graph_outbox SET status='DEAD' WHERE outbox_id=%s", (before[-1]["outbox_id"],)
        )
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        assert queue.claim(leader, lock, ticket).status == "DEAD"
    assert events(world) == before


def test_expired_processing_is_recovered_and_reclaimed_without_double_attempt(world):
    with world.transaction() as connection:
        connection.execute(
            "UPDATE graph_outbox SET status='PROCESSING',attempt_count=2,processing_started_at=statement_timestamp()-interval '1 hour'"
        )
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        assert ProjectionQueue(world).recover_expired(leader) == []
        result = queue.claim(leader, lock, ticket)
        assert result.status == "CLAIMED" and result.event["attempt_count"] == 3
        saved = events(world)
        assert sum(item["status"] == "RETRYABLE" for item in saved) == len(saved) - 1
        assert all(item["attempt_count"] == 2 for item in saved if item["status"] == "RETRYABLE")


@pytest.mark.parametrize("status", ["RETRYABLE", "PROCESSING"])
def test_unexpired_lease_or_future_retry_returns_waiting_not_drained(world, status):
    with world.transaction() as connection:
        connection.execute(
            "UPDATE graph_outbox SET status=%s,attempt_count=2,processing_started_at=statement_timestamp(),next_attempt_at=statement_timestamp()+interval '1 hour'",
            (status,),
        )
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        assert queue.claim(leader, lock, ticket).status == "WAITING"
    assert events(world) == before


def test_attempt_limit_commits_dead_without_starting_another_attempt(world):
    with world.transaction() as connection:
        connection.execute(
            "UPDATE graph_outbox SET status='RETRYABLE',attempt_count=5,next_attempt_at=statement_timestamp()-interval '1 hour'"
        )
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        result = queue.claim(leader, lock, ticket)
        assert result.status == "DEAD" and result.event["attempt_count"] == 5
        assert result.event["processing_started_at"] is None
    assert sum(item["status"] == "DEAD" for item in events(world)) == 1


def test_all_applied_is_drained_without_attempt_changes(world):
    with world.transaction() as connection:
        connection.execute("UPDATE graph_outbox SET status='APPLIED'")
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        assert queue.claim(leader, lock, ticket).status == "DRAINED"
    assert events(world) == before


def test_missing_generation_with_pending_requires_restore_without_consuming_attempts(world):
    with world.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET active_generation=NULL")
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        with pytest.raises(GraphGenerationUnavailable):
            queue.claim(leader, lock, ticket)
    assert events(world) == before


@pytest.mark.parametrize("damage", ["id", "generation", "flag"])
def test_stale_controller_cannot_claim_or_recover(world, damage):
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        if damage == "id":
            ticket = replace(ticket, rebuild_id=uuid4())
        elif damage == "generation":
            ticket = replace(ticket, previous_generation=uuid4())
        else:
            with world.transaction() as connection:
                connection.execute("UPDATE graph_projection_control SET rebuild_flag=false")
        with pytest.raises(RebuildControlRejected):
            queue.claim(leader, lock, ticket)
    assert events(world) == before


@pytest.mark.parametrize("shared", [None, True])
def test_controller_requires_existing_exclusive_lock(world, shared):
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket = RebuildControl(world).begin(leader)
        if shared is not None:
            acquire_graph_mutation_lock(lock, shared=shared)
        with pytest.raises(ValueError, match="exclusive"):
            RebuildQueue(world).claim(leader, lock, ticket)
    assert events(world) == before


def test_empty_initial_seed_has_nothing_to_drain(db):
    db.migrate()
    with graph_leadership(db) as leader, db.transaction() as lock:
        ticket, queue = prepare(db, leader, lock)
        assert ticket.previous_generation is None
        assert queue.claim(leader, lock, ticket).status == "DRAINED"


def test_lost_leadership_cannot_consume_attempt(world):
    before = events(world)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        leader._connection.close()
        with pytest.raises(GraphLeadershipLost):
            queue.claim(leader, lock, ticket)
    assert events(world) == before
