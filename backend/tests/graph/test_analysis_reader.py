"""PG/Neo4j integration for verified-generation analysis, no arbitrary query API."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from neo4j.exceptions import ConstraintError

from graph.test_analysis_gate import budget
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_neo4j_projection import TestLeadership
from graph.test_rebuild_control import store as store
from linescope.application.reads import ToolError
from linescope.graph.analysis_reader import GraphAnalysisReader
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.rebuild_snapshot import RebuildSnapshot
from linescope.persistence.database import Database


@pytest.fixture
def built(store, target):
    driver, generation, adapter = target
    entity_id = str(uuid4())
    snapshot = RebuildSnapshot(
        datetime.now(timezone.utc),
        (
            {
                "entity_type": "Equipment",
                "entity_id": entity_id,
                "entity_version": 7,
                "active": True,
            },
        ),
        (),
    )
    adapter.build(generation=generation, snapshot=snapshot, leadership=TestLeadership())
    with store.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL,rebuild_flag=false",
            (generation,),
        )
    return store, driver, generation, entity_id, snapshot.snapshot_hash


def test_read_is_generation_scoped_verified_and_lock_protected(built):
    db, driver, generation, entity_id, digest = built
    contender = Database(replace(db.settings, lock_ms=50, statement_ms=1000))
    reader = GraphAnalysisReader(db, driver)
    with reader.open(budget()) as read:
        node = read.node("Equipment", entity_id)
        assert node.entity_version == 7 and node.active
        assert read.node("Equipment", str(uuid4())) is None
        assert read.validation.generation == generation and read.validation.snapshot_hash == digest
        assert read.observed_at.tzinfo is timezone.utc
        with pytest.raises(psycopg.errors.LockNotAvailable), contender.transaction() as c:
            acquire_graph_mutation_lock(c, shared=False)
    with pytest.raises(RuntimeError, match="closed"):
        read.node("Equipment", entity_id)
    with contender.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)


@pytest.mark.parametrize("damage", ["missing", "unvalidated", "hash", "time"])
def test_bad_generation_refuses_context_entry(built, damage):
    db, driver, generation, _, _ = built
    queries = {
        "missing": "MATCH (g:LineScopeGeneration {generation:$generation}) DELETE g",
        "unvalidated": "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated=false",
        "hash": "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.snapshot_hash='bad'",
        "time": "MATCH (g:LineScopeGeneration {generation:$generation}) REMOVE g.validated_at",
        "duplicate": "CREATE (:LineScopeGeneration {generation:$generation})",
    }
    with driver.session() as session:
        session.run(queries[damage], generation=generation).consume()
    with pytest.raises(ToolError) as caught, GraphAnalysisReader(db, driver).open(budget()):
        pytest.fail("Invalid marker must reject entry")
    assert caught.value.code == "GRAPH_UNAVAILABLE"


def test_end_gate_discards_graph_result_when_rebuild_begins(built):
    db, driver, _, entity_id, _ = built
    with pytest.raises(ToolError) as caught:
        with GraphAnalysisReader(db, driver).open(budget()) as read:
            assert read.node("Equipment", entity_id).entity_version == 7
            with db.transaction() as c:
                c.execute("UPDATE graph_projection_control SET rebuild_flag=true")
    assert caught.value.code == "GRAPH_REBUILDING"


@pytest.mark.parametrize("entity_type", ["Equipment` MATCH (n) DELETE n //", "Unknown"])
def test_entity_type_is_fixed_allowlist(built, entity_type):
    db, driver, _, entity_id, _ = built
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        with pytest.raises(ValueError):
            read.node(entity_type, entity_id)
        assert read.node("Equipment", entity_id).entity_version == 7


def test_invalid_id_cannot_change_query_structure(built):
    db, driver, _, entity_id, _ = built
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        with pytest.raises(ValueError):
            read.node("Equipment", "' OR 1=1 --")
        assert read.node("Equipment", entity_id).entity_version == 7


@pytest.mark.parametrize("damage", ["version", "active"])
def test_corrupt_node_is_not_returned_as_valid_fact(built, damage):
    db, driver, generation, entity_id, _ = built
    queries = {
        "duplicate": "CREATE (:LineScopeEntity {generation:$generation,entity_type:'Equipment',entity_id:$id,entity_version:7,active:true})",
        "version": "MATCH (n:LineScopeEntity {generation:$generation,entity_id:$id}) SET n.entity_version=0",
        "active": "MATCH (n:LineScopeEntity {generation:$generation,entity_id:$id}) REMOVE n.active",
    }
    with driver.session() as session:
        session.run(queries[damage], generation=generation, id=entity_id).consume()
    with pytest.raises(ToolError) as caught:
        with GraphAnalysisReader(db, driver).open(budget()) as read:
            read.node("Equipment", entity_id)
    assert caught.value.code == "GRAPH_UNAVAILABLE"


def test_inactive_registration_is_preserved_not_inferred_as_availability(built):
    db, driver, generation, entity_id, _ = built
    with driver.session() as session:
        session.run(
            "MATCH (n:LineScopeEntity {generation:$generation,entity_id:$id}) SET n.active=false",
            generation=generation,
            id=entity_id,
        ).consume()
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        assert read.node("Equipment", entity_id).active is False


@pytest.mark.parametrize("kind", ["marker", "node"])
def test_database_uniqueness_rejects_duplicate_graph_facts(built, kind):
    db, driver, generation, entity_id, _ = built
    query = (
        "CREATE (:LineScopeGeneration {generation:$generation})"
        if kind == "marker"
        else "CREATE (:LineScopeEntity {generation:$generation,entity_type:'Equipment',entity_id:$id,entity_version:7,active:true})"
    )
    with driver.session() as session, pytest.raises(ConstraintError):
        session.run(query, generation=generation, id=entity_id).consume()
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        assert read.node("Equipment", entity_id).entity_version == 7
