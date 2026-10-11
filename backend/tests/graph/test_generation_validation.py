"""Durable validation evidence is distinct from current synchronization."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from neo4j.exceptions import ConstraintError

from graph.test_neo4j_generation import build
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_neo4j_projection import TestLeadership
from graph.test_projection_queue import ordered
from graph.test_projection_queue import queued as queued
from graph.test_rebuild_control import row
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.neo4j_generation import Neo4jGeneration
from linescope.graph.neo4j_projection import GraphGenerationUnavailable, ProjectionIntegrityError
from linescope.graph.rebuild_control import RebuildControl, RebuildControlRejected
from linescope.graph.rebuild_snapshot import RebuildSnapshot


def empty_snapshot():
    return RebuildSnapshot(datetime.now(timezone.utc), (), ())


def marker(target):
    driver, generation, _ = target
    with driver.session() as session:
        return dict(
            session.run(
                "MATCH (g:LineScopeGeneration {generation:$generation}) RETURN properties(g) AS props",
                generation=generation,
            ).single(strict=True)["props"]
        )


def test_observe_returns_committed_build_hash_and_time_without_changes(target):
    result = build(target, empty_snapshot())
    before = marker(target)
    _, generation, adapter = target
    validation = adapter.observe_validation(
        generation=UUID(generation), leadership=TestLeadership()
    )
    assert validation.generation == generation
    assert validation.snapshot_hash == result.snapshot_hash
    assert validation.validated_at == before["validated_at"].to_native()
    assert validation.validated_at.tzinfo == timezone.utc
    assert marker(target) == before
    assert (
        adapter.require_verified(
            generation=generation,
            snapshot_hash=validation.snapshot_hash,
            leadership=TestLeadership(),
        )
        is None
    )


@pytest.mark.parametrize("damage", ["missing", "unvalidated", "missing_time"])
def test_missing_or_unvalidated_evidence_is_unavailable(target, damage):
    _, generation, adapter = target
    if damage != "missing":
        build(target, empty_snapshot())
        driver = target[0]
        query = {
            "unvalidated": "SET g.validated=false",
            "missing_time": "REMOVE g.validated_at",
        }[damage]
        with driver.session() as session:
            session.run(
                "MATCH (g:LineScopeGeneration {generation:$generation}) " + query,
                generation=generation,
            ).consume()
    with pytest.raises(GraphGenerationUnavailable):
        adapter.observe_validation(generation=generation, leadership=TestLeadership())


@pytest.mark.parametrize("bad_hash", [None, "bad", "A" * 64, 17])
def test_invalid_stored_hash_is_rejected(target, bad_hash):
    build(target, empty_snapshot())
    driver, generation, adapter = target
    with driver.session() as session:
        session.run(
            "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.snapshot_hash=$hash",
            generation=generation,
            hash=bad_hash,
        ).consume()
    with pytest.raises(ProjectionIntegrityError, match="hash"):
        adapter.observe_validation(generation=generation, leadership=TestLeadership())


@pytest.mark.parametrize("value", ["yesterday", datetime(2026, 10, 11)])
def test_invalid_validation_time_is_rejected(target, value):
    build(target, empty_snapshot())
    driver, generation, adapter = target
    with driver.session() as session:
        session.run(
            "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated_at=$value",
            generation=generation,
            value=value,
        ).consume()
    with pytest.raises(ProjectionIntegrityError, match="time"):
        adapter.observe_validation(generation=generation, leadership=TestLeadership())


def test_duplicate_marker_is_rejected_by_graph_constraint(target):
    build(target, empty_snapshot())
    driver, generation, adapter = target
    before = marker(target)
    with driver.session() as session, pytest.raises(ConstraintError):
        session.run(
            "MATCH (g:LineScopeGeneration {generation:$generation}) "
            "CREATE (copy:LineScopeGeneration) SET copy=properties(g)",
            generation=generation,
        ).consume()
    assert marker(target) == before
    assert (
        adapter.observe_validation(generation=generation, leadership=TestLeadership()).snapshot_hash
        == before["snapshot_hash"]
    )


def test_ambiguous_adapter_result_is_rejected_before_commit():
    # Defensive boundary for a store whose generation constraint is absent.
    tx = SimpleNamespace(
        run=lambda *args, **kwargs: [{}, {}],
        commit=lambda: pytest.fail("Ambiguous evidence must not be accepted"),
    )
    session = SimpleNamespace(begin_transaction=lambda **kwargs: nullcontext(tx))
    driver = SimpleNamespace(session=lambda **kwargs: nullcontext(session))
    with pytest.raises(ProjectionIntegrityError, match="Ambiguous"):
        Neo4jGeneration(driver).observe_validation(generation=uuid4(), leadership=TestLeadership())


def test_observed_evidence_can_resume_but_is_rechecked_against_actual_graph(queued, target):
    db, _, _ = queued
    control = RebuildControl(db)
    result = build(target, empty_snapshot())
    driver, generation, adapter = target
    with db.transaction() as c:
        c.execute("UPDATE graph_projection_control SET active_generation=%s", (UUID(generation),))
    with graph_leadership(db) as leader, db.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        old = control.begin(leader)
        observation = control.observe(leader, lock)
        assert observation.recovery_ticket() == old
        proof = adapter.observe_validation(
            generation=observation.active_generation, leadership=leader
        )
        before, events = row(db), ordered(db)
        with pytest.raises(RebuildControlRejected):
            control.resume(
                leader, lock, old, verified=replace(proof, generation=str(uuid4())), adapter=adapter
            )
        with pytest.raises(ProjectionIntegrityError):
            control.resume(
                leader, lock, old, verified=replace(proof, snapshot_hash="f" * 64), adapter=adapter
            )
        with driver.session() as session:
            session.run(
                "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated=false",
                generation=generation,
            ).consume()
        with pytest.raises(GraphGenerationUnavailable):
            control.resume(leader, lock, old, verified=proof, adapter=adapter)
        assert row(db) == before and ordered(db) == events
        with driver.session() as session:
            session.run(
                "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated=true",
                generation=generation,
            ).consume()
        resumed = control.resume(leader, lock, old, verified=proof, adapter=adapter)
        assert resumed.previous_generation == UUID(result.generation)
        assert resumed.rebuild_id != old.rebuild_id
        assert row(db)["rebuild_flag"] and ordered(db) == events
        assert control.fail(leader, resumed)


@pytest.mark.parametrize("failure_at", [1, 2, 3])
def test_observation_rejects_leadership_loss_at_each_boundary(target, failure_at):
    build(target, empty_snapshot())
    _, generation, adapter = target

    class LosingLeader:
        calls = 0

        def require(self):
            self.calls += 1
            if self.calls == failure_at:
                raise GraphLeadershipLost("lost")

    before = marker(target)
    with pytest.raises(GraphLeadershipLost):
        adapter.observe_validation(generation=generation, leadership=LosingLeader())
    assert marker(target) == before


@pytest.mark.parametrize("generation", ["' OR 1=1 --", "x'}) DETACH DELETE g //", "", None])
def test_invalid_generation_is_rejected_without_modifying_graph(target, generation):
    build(target, empty_snapshot())
    before = marker(target)
    with pytest.raises(ValueError):
        target[2].observe_validation(generation=generation, leadership=TestLeadership())
    assert marker(target) == before
