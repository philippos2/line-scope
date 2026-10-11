"""Real PG drain budget boundaries and adapter-commit / ACK separation."""

from contextlib import ExitStack

import psycopg
import pytest

from graph.test_projection_application import RecordingAdapter, stored
from graph.test_projection_queue import queued as queued
from graph.test_rebuild_drain import Clock
from graph.test_rebuild_queue import prepare
from graph.test_rebuild_queue import world as world
from linescope.graph.graph_leadership import graph_leadership
from linescope.graph.rebuild_application import RebuildApplication
from linescope.graph.rebuild_drain import DeadlineLeadership
from linescope.graph.transaction_timeout import GraphTransactionBudgetExpired
from linescope.persistence.core_timeouts import read_timeout_limits


def deadline(leader, clock, seconds):
    return DeadlineLeadership(leader, clock.now + seconds, clock)


def test_queue_claim_and_failure_transactions_receive_budget(world, monkeypatch):
    import linescope.graph.postgres_timeout as module

    original = module.cap_postgres_transaction
    seen = []

    def inspect(connection, leadership):
        original(connection, leadership)
        seen.append(read_timeout_limits(connection))

    monkeypatch.setattr(module, "cap_postgres_transaction", inspect)
    clock = Clock()
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        guarded = deadline(leader, clock, 0.2)
        event = queue.claim(guarded, lock, ticket).event
        assert queue.fail(guarded, lock, ticket, event)
        assert stored(world, event)["status"] == "RETRYABLE"
    assert seen == [{"statement_timeout": 200, "lock_timeout": 200}] * 2


def test_ack_recomputes_remaining_budget_after_adapter_commit(world, monkeypatch):
    import linescope.graph.postgres_timeout as module

    original = module.cap_postgres_transaction
    seen = []
    clock = Clock()

    def inspect(connection, leadership):
        original(connection, leadership)
        seen.append(read_timeout_limits(connection))

    monkeypatch.setattr(module, "cap_postgres_transaction", inspect)
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        guarded = deadline(leader, clock, 2)
        adapter = RecordingAdapter(lambda arguments: setattr(clock, "now", clock.now + 1.5))
        assert RebuildApplication(world).apply(guarded, lock, ticket, event, adapter)
        assert stored(world, event)["status"] == "APPLIED"
        assert len(adapter.calls) == 1
    assert seen == [
        {"statement_timeout": 2000, "lock_timeout": 2000},
        {"statement_timeout": 500, "lock_timeout": 500},
    ]


def test_ack_lock_timeout_preserves_processing_and_does_not_repeat_adapter(world):
    clock = Clock()
    with graph_leadership(world) as leader, world.transaction() as lock, ExitStack() as blockers:
        ticket, queue = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        before = stored(world, event)

        def block_ack(arguments):
            holder = blockers.enter_context(world.transaction())
            holder.execute(
                "SELECT outbox_id FROM graph_outbox WHERE outbox_id=%s FOR UPDATE",
                (event["outbox_id"],),
            ).fetchone()

        adapter = RecordingAdapter(block_ack)
        with pytest.raises((psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled)):
            RebuildApplication(world).apply(
                deadline(leader, clock, 0.1), lock, ticket, event, adapter
            )
        assert stored(world, event) == before
        assert len(adapter.calls) == 1
    assert stored(world, event)["status"] == "PROCESSING"


def test_insufficient_read_budget_prevents_adapter_io(world):
    clock = Clock()
    with graph_leadership(world) as leader, world.transaction() as lock:
        ticket, queue = prepare(world, leader, lock)
        event = queue.claim(leader, lock, ticket).event
        before = stored(world, event)
        adapter = RecordingAdapter()
        with pytest.raises(GraphTransactionBudgetExpired):
            RebuildApplication(world).apply(
                deadline(leader, clock, 0.0009), lock, ticket, event, adapter
            )
        assert adapter.calls == []
        assert stored(world, event) == before
