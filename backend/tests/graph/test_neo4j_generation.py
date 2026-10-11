from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graph.test_neo4j_projection import TestLeadership
from graph.test_neo4j_projection import graph_driver as graph_driver
from graph.test_rebuild_snapshot import world as world
from linescope.graph.graph_leadership import GraphLeadershipLost
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.neo4j_generation import Neo4jGeneration
from linescope.graph.neo4j_projection import Neo4jProjection, ProjectionIntegrityError
from linescope.graph.projection_payload import build_projection_payload
from linescope.graph.rebuild_snapshot import RebuildSnapshot, read_rebuild_snapshot


@pytest.fixture
def target(graph_driver):
    generation = str(uuid4())
    try:
        yield graph_driver, generation, Neo4jGeneration(graph_driver)
    finally:
        with graph_driver.session() as session:
            session.run(
                "MATCH (n {generation:$generation}) DETACH DELETE n", generation=generation
            ).consume()


@pytest.fixture
def source(world):
    with world.transaction() as connection:
        acquire_graph_mutation_lock(connection, shared=False)
        connection.execute("UPDATE dependency_relation SET active=false")
        return read_rebuild_snapshot(connection)


def build(target, snapshot, leadership=None):
    _, generation, adapter = target
    return adapter.build(
        generation=generation, snapshot=snapshot, leadership=leadership or TestLeadership()
    )


def count(target):
    driver, generation, _ = target
    with driver.session() as session:
        return session.run(
            "MATCH (n {generation:$generation}) RETURN count(n) AS n", generation=generation
        ).single()["n"]


def test_build_checks_all_source_facts_before_verified_marker(target, source):
    result = build(target, source)
    assert result.snapshot_hash == source.snapshot_hash
    assert result.node_count == len(source.nodes)
    assert result.aggregate_count == len(source.aggregates)
    driver, generation, _ = target
    with driver.session() as session:
        marker = session.run(
            "MATCH (g:LineScopeGeneration {generation:$generation}) RETURN properties(g) AS p",
            generation=generation,
        ).single()["p"]
        assert marker["validated"] is True and marker["snapshot_hash"] == source.snapshot_hash
        assert marker["validated_at"] is not None
        nodes = session.run(
            "MATCH (n:LineScopeEntity {generation:$generation}) RETURN n.active AS active",
            generation=generation,
        )
        assert any(row["active"] is False for row in nodes)
        edges = list(
            session.run(
                "MATCH ()-[r]->() WHERE r.generation=$generation RETURN r.active AS active,r.source_outbox_id AS outbox,r.source_rebuild_id AS rebuild",
                generation=generation,
            )
        )
        assert any(row["active"] is False for row in edges)
        assert all(row["outbox"] is None and row["rebuild"] == generation for row in edges)


def test_empty_generation_is_verified(target):
    result = build(target, RebuildSnapshot(datetime.now(timezone.utc), (), ()))
    assert result.node_count == result.aggregate_count == 0
    assert count(target) == 1


def test_existing_generation_is_never_overwritten(target, source):
    build(target, source)
    before = count(target)
    with pytest.raises(ProjectionIntegrityError, match="already exists"):
        build(target, source)
    assert count(target) == before


@pytest.mark.parametrize("damage", ["node", "edge", "marker", "generation", "extra_node"])
def test_verification_failure_rolls_back_entire_new_generation(target, source, monkeypatch, damage):
    _, _, adapter = target
    original = adapter._verify

    def corrupt(tx, generation, *args):
        queries = {
            "extra_node": "CREATE (:Unexpected {generation:$generation})",
            "node": "MATCH (n:LineScopeEntity {generation:$generation}) SET n.entity_version=999",
            "edge": "MATCH ()-[r]->() WHERE r.generation=$generation SET r.active=true",
            "marker": "MATCH (m:LineScopeProjectionMarker {generation:$generation}) SET m.payload_hash='bad'",
            "generation": "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.snapshot_hash='bad'",
        }
        tx.run(queries[damage], generation=generation).consume()
        original(tx, generation, *args)

    monkeypatch.setattr(adapter, "_verify", corrupt)
    with pytest.raises(ProjectionIntegrityError):
        build(target, source)
    assert count(target) == 0


def test_leader_loss_before_commit_rolls_back(target, source, monkeypatch):
    _, _, adapter = target
    leader = TestLeadership()
    original = adapter._verify

    def lose(*args):
        original(*args)
        leader.alive = False

    monkeypatch.setattr(adapter, "_verify", lose)
    with pytest.raises(GraphLeadershipLost):
        build(target, source, leader)
    assert count(target) == 0


@pytest.mark.parametrize("damage", ["duplicate_node", "missing_endpoint", "duplicate_aggregate"])
def test_invalid_snapshot_is_not_materialized(target, source, damage):
    damaged = {
        "duplicate_node": replace(source, nodes=source.nodes + source.nodes[:1]),
        "missing_endpoint": replace(source, nodes=()),
        "duplicate_aggregate": replace(
            source, aggregates=source.aggregates + source.aggregates[:1]
        ),
    }[damage]
    with pytest.raises(ValueError):
        build(target, damaged)
    assert count(target) == 0


def test_worker_replay_and_new_version_after_rebuild(target, source):
    build(target, source)
    driver, generation, _ = target
    adapter = Neo4jProjection(driver)
    payload = source.aggregates[0]
    before = count(target)
    adapter.apply(
        generation=generation, outbox_id=uuid4(), payload=payload, leadership=TestLeadership()
    )
    assert count(target) == before
    state = dict(payload["state"], version=payload["aggregate_version"] + 1)
    newer = build_projection_payload(payload["aggregate_type"], state)
    delivery = str(uuid4())
    adapter.apply(
        generation=generation, outbox_id=delivery, payload=newer, leadership=TestLeadership()
    )
    with driver.session() as session:
        marker = session.run(
            "MATCH (m:LineScopeProjectionMarker {generation:$generation,aggregate_type:$kind,aggregate_id:$id}) RETURN properties(m) AS p",
            generation=generation,
            kind=payload["aggregate_type"],
            id=payload["aggregate_id"],
        ).single()["p"]
        assert marker["source_outbox_id"] == delivery
        assert "source_rebuild_id" not in marker
        assert marker["source_version"] == newer["aggregate_version"]


@pytest.mark.parametrize(
    "damage", ["missing_source", "wrong_generation", "ambiguous_source", "invalid_snapshot_hash"]
)
def test_worker_rejects_invalid_rebuild_provenance(target, source, damage):
    build(target, source)
    driver, generation, _ = target
    with driver.session() as session:
        queries = {
            "missing_source": "MATCH (m:LineScopeProjectionMarker {generation:$generation}) REMOVE m.source_rebuild_id",
            "wrong_generation": "MATCH (m:LineScopeProjectionMarker {generation:$generation}) SET m.source_rebuild_id=$other",
            "ambiguous_source": "MATCH (m:LineScopeProjectionMarker {generation:$generation}) SET m.source_outbox_id=$other",
            "invalid_snapshot_hash": "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.snapshot_hash='bad'",
        }
        session.run(queries[damage], generation=generation, other=str(uuid4())).consume()
    with pytest.raises(ProjectionIntegrityError):
        Neo4jProjection(driver).apply(
            generation=generation,
            outbox_id=uuid4(),
            payload=source.aggregates[0],
            leadership=TestLeadership(),
        )


def test_worker_rejects_same_version_different_state_after_rebuild(target, source):
    build(target, source)
    payload = source.aggregates[0]
    state = dict(payload["state"], active=not payload["state"]["active"])
    changed = build_projection_payload(payload["aggregate_type"], state)
    driver, generation, _ = target
    with pytest.raises(ProjectionIntegrityError, match="different"):
        Neo4jProjection(driver).apply(
            generation=generation, outbox_id=uuid4(), payload=changed, leadership=TestLeadership()
        )
