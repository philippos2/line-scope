"""Budget policy and real Neo4j transaction boundaries, including server rollback."""

from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
from neo4j.exceptions import Neo4jError

from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_neo4j_projection import TestLeadership, facts, relation, seed_endpoints
from graph.test_neo4j_projection import graph as graph
from graph.test_rebuild_controller import adapters as adapters
from graph.test_rebuild_controller import controller
from graph.test_rebuild_controller import empty as empty
from graph.test_rebuild_drain import Clock
from linescope.graph.graph_leadership import graph_leadership
from linescope.graph.neo4j_generation import Neo4jGeneration
from linescope.graph.neo4j_projection import Neo4jProjection
from linescope.graph.projection_payload import build_projection_payload
from linescope.graph.projection_state import ProjectionState
from linescope.graph.rebuild_drain import DeadlineLeadership, RebuildDrainTimeout
from linescope.graph.rebuild_snapshot import RebuildSnapshot
from linescope.graph.transaction_timeout import (
    GraphTransactionBudgetExpired,
    neo4j_transaction_timeout,
)


class RecordingDriver:
    """Forward all real transactions; record only the timeout boundary."""

    def __init__(self, driver, on_session=None):
        self.driver, self.on_session, self.timeouts = driver, on_session, []

    @contextmanager
    def session(self, **kwargs):
        with self.driver.session(**kwargs) as session:
            if self.on_session:
                self.on_session()

            def begin(**options):
                self.timeouts.append(options["timeout"])
                return session.begin_transaction(**options)

            yield SimpleNamespace(begin_transaction=begin)


@pytest.mark.parametrize("configured", [0, -1, True, float("inf"), float("nan")])
def test_invalid_timeout_cannot_disable_server_limit(configured):
    with pytest.raises(ValueError):
        neo4j_transaction_timeout(TestLeadership(), configured)


def test_normal_leadership_preserves_configured_timeout():
    assert neo4j_transaction_timeout(TestLeadership(), 10) == 10


@pytest.mark.parametrize("budget", [0, -1, True, float("inf"), float("nan"), 0.0009])
def test_invalid_or_submillisecond_budget_is_rejected(budget):
    leadership = SimpleNamespace(remaining=lambda: budget)
    with pytest.raises(GraphTransactionBudgetExpired):
        neo4j_transaction_timeout(leadership, 10)


def test_budget_is_rounded_down_and_cannot_extend_configured_timeout():
    assert neo4j_transaction_timeout(SimpleNamespace(remaining=lambda: 1.2349), 10) == 1.234
    assert neo4j_transaction_timeout(SimpleNamespace(remaining=lambda: 10), 0.5) == 0.5


def test_nested_deadline_cannot_extend_parent_budget():
    clock = Clock()
    parent = DeadlineLeadership(TestLeadership(), clock.now + 0.75, clock)
    child = DeadlineLeadership(parent, clock.now + 20, clock)
    assert neo4j_transaction_timeout(child, 10) == 0.75
    clock.now += 0.75
    with pytest.raises(RebuildDrainTimeout):
        neo4j_transaction_timeout(child, 10)


@pytest.mark.parametrize("phase", ["build", "observe", "verify"])
def test_generation_phases_bound_real_transaction_by_budget_at_begin(target, phase):
    driver, generation, _ = target
    clock = Clock()
    snapshot = RebuildSnapshot(datetime.now(timezone.utc), (), ())
    if phase != "build":
        Neo4jGeneration(driver).build(
            generation=generation, snapshot=snapshot, leadership=TestLeadership()
        )
    # Time spent entering the session is included before BEGIN's limit is computed.
    recording = RecordingDriver(driver, on_session=lambda: setattr(clock, "now", clock.now + 1))
    adapter = Neo4jGeneration(recording)
    guard = DeadlineLeadership(TestLeadership(), clock.now + 3, clock)
    if phase == "build":
        result = adapter.build(generation=generation, snapshot=snapshot, leadership=guard)
        assert result.snapshot_hash == snapshot.snapshot_hash
    elif phase == "observe":
        assert (
            adapter.observe_validation(generation=generation, leadership=guard).snapshot_hash
            == snapshot.snapshot_hash
        )
    else:
        adapter.require_verified(
            generation=generation, snapshot_hash=snapshot.snapshot_hash, leadership=guard
        )
    assert recording.timeouts == [2]
    assert adapter.timeout_seconds == 10


@pytest.mark.parametrize("phase", ["build", "observe"])
def test_expiry_while_entering_session_never_begins_graph_transaction(target, phase):
    driver, generation, _ = target
    clock = Clock()
    recording = RecordingDriver(driver, on_session=lambda: setattr(clock, "now", clock.now + 3))
    adapter = Neo4jGeneration(recording)
    guard = DeadlineLeadership(TestLeadership(), clock.now + 2, clock)
    with pytest.raises(RebuildDrainTimeout):
        if phase == "build":
            adapter.build(
                generation=generation,
                snapshot=RebuildSnapshot(datetime.now(timezone.utc), (), ()),
                leadership=guard,
            )
        else:
            adapter.observe_validation(generation=generation, leadership=guard)
    assert recording.timeouts == []


def test_remaining_budget_terminates_real_projection_lock_wait_and_rolls_back(graph):
    driver, generation, adapter = graph
    payload = build_projection_payload("DependencyRelation", relation())
    seed_endpoints(graph, payload)
    adapter.apply(
        generation=generation, outbox_id=uuid4(), payload=payload, leadership=TestLeadership()
    )
    before = facts(graph)
    recording = RecordingDriver(driver)
    bounded = Neo4jProjection(recording)
    with driver.session() as session, session.begin_transaction() as holder:
        holder.run(
            "MATCH (m:LineScopeProjectionMarker {generation:$generation}) SET m._test_lock=true",
            generation=generation,
        ).consume()
        guard = DeadlineLeadership(TestLeadership(), monotonic() + 0.5, monotonic)
        with pytest.raises(Neo4jError):
            bounded.apply(
                generation=generation, outbox_id=uuid4(), payload=payload, leadership=guard
            )
        holder.rollback()
    assert len(recording.timeouts) == 1 and 0 < recording.timeouts[0] <= 0.5
    assert bounded.timeout_seconds == 10
    assert facts(graph) == before


def test_controller_propagates_one_budget_through_build_and_publication(empty, adapters):
    clock = Clock()
    calls = []

    def consume_time():
        clock.now += 58 if not calls else 1
        calls.append(clock.now)

    recording = RecordingDriver(adapters[1].driver, on_session=consume_time)
    generation = Neo4jGeneration(recording)
    service, _ = controller(empty, (adapters[0], generation), clock=clock, wait=clock.wait)
    with graph_leadership(empty) as leader:
        service.run(leader)
    assert recording.timeouts == [2, 1]
    assert ProjectionState(empty).observe().status == "CURRENT"
    assert generation.timeout_seconds == 10
