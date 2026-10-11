"""Virtual-clock scheduling, real PG lock fences and real Neo4j drainage."""

from contextlib import contextmanager
from uuid import UUID

import pytest
from psycopg.pq import TransactionStatus

from graph.test_neo4j_projection import graph as graph
from graph.test_neo4j_projection import graph_driver as graph_driver
from graph.test_neo4j_projection import seed_endpoints
from graph.test_outbox import events
from graph.test_projection_application import RecordingAdapter
from graph.test_projection_queue import queued as queued
from graph.test_rebuild_queue import world as world
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.rebuild_control import RebuildControl
from linescope.graph.rebuild_drain import RebuildDrain, RebuildDrainStopped, RebuildDrainTimeout
from linescope.graph.rebuild_step import RebuildStep, RebuildStepResult


class Clock:
    def __init__(self):
        self.now, self.waits = 100.0, []

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class ScriptedStep:
    """Scheduling double; not proof of Outbox or Graph application."""

    def __init__(self, statuses, action=None):
        self.statuses, self.calls, self.action = iter(statuses), 0, action

    def run_once(self, leader, lock, ticket):
        self.calls += 1
        if self.action:
            self.action(leader, lock, ticket)
        return RebuildStepResult(next(self.statuses), UUID(int=self.calls))


@contextmanager
def owned(db, *, shared=False):
    with graph_leadership(db) as leader, db.transaction() as lock:
        ticket = RebuildControl(db).begin(leader)
        if shared is not None:
            acquire_graph_mutation_lock(lock, shared=shared)
        yield leader, lock, ticket


@pytest.fixture
def prepared(db):
    db.migrate()
    return db


def test_wait_retry_progress_and_drained_only_success(prepared):
    clock = Clock()
    step = ScriptedStep(["WAITING", "RETRYABLE", "APPLIED", "APPLIED", "DRAINED"])
    with owned(prepared) as (leader, lock, ticket):
        result = RebuildDrain(step, clock=clock, wait=clock.wait).run(
            leader, lock, ticket, deadline=110
        )
        assert result.applied_count == 2 and step.calls == 5 and clock.waits == [1, 1]
        assert lock.info.transaction_status == TransactionStatus.INTRANS


def test_wait_capped_to_remaining_budget_and_expiry_never_restarts_deadline(prepared):
    clock = Clock()
    step = ScriptedStep(["WAITING"] * 5)
    with owned(prepared) as (leader, lock, ticket):
        with pytest.raises(RebuildDrainTimeout):
            RebuildDrain(step, clock=clock, wait=clock.wait).run(
                leader, lock, ticket, deadline=102.5
            )
        assert step.calls == 3 and clock.waits == [1, 1, 0.5]
        assert lock.info.transaction_status == TransactionStatus.INTRANS


@pytest.mark.parametrize("status", ["DEAD", "FENCED"])
def test_stop_states_never_wait_or_continue(prepared, status):
    clock, step = Clock(), ScriptedStep([status, "DRAINED"])
    with owned(prepared) as (leader, lock, ticket):
        with pytest.raises(RebuildDrainStopped) as failure:
            RebuildDrain(step, clock=clock, wait=clock.wait).run(leader, lock, ticket, deadline=110)
    assert failure.value.status == status and failure.value.outbox_id == UUID(int=1)
    assert step.calls == 1 and not clock.waits


@pytest.mark.parametrize("status", ["APPLIED", "DRAINED"])
def test_late_step_result_never_accepted(prepared, status):
    clock = Clock()

    def expire(*_):
        clock.now = 110

    step = ScriptedStep([status, "DRAINED"], expire)
    with owned(prepared) as (leader, lock, ticket):
        with pytest.raises(RebuildDrainTimeout):
            RebuildDrain(step, clock=clock, wait=clock.wait).run(leader, lock, ticket, deadline=110)
    assert step.calls == 1


@pytest.mark.parametrize("shared", [None, True])
def test_requires_existing_exclusive_lock_before_step(prepared, shared):
    clock, step = Clock(), ScriptedStep(["DRAINED"])
    with owned(prepared, shared=shared) as (leader, lock, ticket):
        with pytest.raises(ValueError, match="exclusive"):
            RebuildDrain(step, clock=clock, wait=clock.wait).run(leader, lock, ticket, deadline=110)
    assert step.calls == 0


@pytest.mark.parametrize("loss", ["leader", "lock"])
def test_loss_while_waiting_stops_before_next_step(prepared, loss):
    clock, step = Clock(), ScriptedStep(["WAITING", "DRAINED"])
    with owned(prepared) as (leader, lock, ticket):

        def wait(seconds):
            clock.wait(seconds)
            (leader._connection if loss == "leader" else lock).close()

        with pytest.raises((GraphLeadershipLost, ValueError)):
            RebuildDrain(step, clock=clock, wait=wait).run(leader, lock, ticket, deadline=110)
    assert step.calls == 1


def test_unknown_exception_propagates_without_scheduling_retry(prepared):
    clock = Clock()

    def fail(*_):
        raise RuntimeError("unknown failure")

    step = ScriptedStep(["DRAINED"], fail)
    with owned(prepared) as (leader, lock, ticket):
        with pytest.raises(RuntimeError, match="unknown failure"):
            RebuildDrain(step, clock=clock, wait=clock.wait).run(leader, lock, ticket, deadline=110)
    assert step.calls == 1 and not clock.waits


def test_unexpected_status_never_completes(prepared):
    clock = Clock()
    with owned(prepared) as (leader, lock, ticket):
        with pytest.raises(RuntimeError, match="Unexpected"):
            RebuildDrain(ScriptedStep(["IDLE"]), clock=clock).run(
                leader, lock, ticket, deadline=110
            )


@pytest.mark.parametrize("deadline", [100, 99])
def test_expired_entry_never_calls_step(prepared, deadline):
    clock, step = Clock(), ScriptedStep(["DRAINED"])
    with owned(prepared) as (leader, lock, ticket):
        with pytest.raises(RebuildDrainTimeout):
            RebuildDrain(step, clock=clock).run(leader, lock, ticket, deadline=deadline)
    assert step.calls == 0


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), "110"])
def test_invalid_deadline_rejected(prepared, deadline):
    with owned(prepared) as (leader, lock, ticket):
        with pytest.raises(ValueError, match="deadline"):
            RebuildDrain(ScriptedStep(["DRAINED"])).run(leader, lock, ticket, deadline=deadline)


@pytest.mark.parametrize("poll", [False, 0, -1, float("inf"), float("nan")])
def test_invalid_poll_rejected(poll):
    with pytest.raises(ValueError):
        RebuildDrain(ScriptedStep(["DRAINED"]), poll_seconds=poll)


def test_real_graph_drained_preserves_control_and_caller_lock(world, graph):
    _, generation, adapter = graph
    with world.transaction() as c:
        c.execute("UPDATE graph_projection_control SET active_generation=%s", (UUID(generation),))
    for event in events(world):
        seed_endpoints(graph, event["payload"])
    clock = Clock()
    with owned(world) as (leader, lock, ticket):
        result = RebuildDrain(RebuildStep(world, adapter), clock=clock, wait=clock.wait).run(
            leader, lock, ticket, deadline=160
        )
        assert result.applied_count == 3 and not clock.waits
        assert all(row["status"] == "APPLIED" for row in events(world))
        assert lock.info.transaction_status == TransactionStatus.INTRANS
        with world.transaction() as c:
            control = c.execute("SELECT * FROM graph_projection_control").fetchone()
        assert control["rebuild_flag"] and control["fatal_error"] == "NOT_INITIALIZED"
        assert control["active_generation"] == UUID(generation)


def test_expiry_during_external_apply_never_acks_or_manufactures_dead(world):
    clock = Clock()

    def expire(arguments):
        clock.now = 160

    adapter = RecordingAdapter(expire)
    with owned(world) as (leader, lock, ticket):
        with pytest.raises(RebuildDrainTimeout):
            RebuildDrain(RebuildStep(world, adapter), clock=clock, wait=clock.wait).run(
                leader, lock, ticket, deadline=160
            )
        assert lock.info.transaction_status == TransactionStatus.INTRANS
    assert len(adapter.calls) == 1
    assert sum(row["status"] == "PROCESSING" for row in events(world)) == 1
    assert all(row["status"] not in {"APPLIED", "DEAD"} for row in events(world))
