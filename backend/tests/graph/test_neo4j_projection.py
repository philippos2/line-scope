"""Disposable real Neo4j integration, plus PG acknowledgement replay."""

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ConstraintError, Neo4jError
from test_assignments import row as assignment
from test_relation_snapshot import current as relation

from graph.test_projection_queue import queued as queued
from linescope.graph.graph_leadership import GraphLeadershipLost, graph_leadership
from linescope.graph.neo4j_projection import (
    GraphGenerationUnavailable,
    Neo4jProjection,
    ProjectionIntegrityError,
    install_projection_schema,
)
from linescope.graph.projection_application import ProjectionApplication
from linescope.graph.projection_payload import build_projection_payload, projection_payload_hash


class TestLeadership:
    __test__ = False

    def __init__(self):
        self.alive = True

    def require(self):
        if not self.alive:
            raise GraphLeadershipLost("Test leadership lost")


@pytest.fixture(scope="module")
def graph_driver():
    uri = os.getenv("LINESCOPE_TEST_NEO4J_URI")
    if not uri:
        pytest.skip("Set LINESCOPE_TEST_NEO4J_URI for disposable Neo4j tests")
    with GraphDatabase.driver(uri, auth=("neo4j", "disposable-graph-password")) as driver:
        driver.verify_connectivity()
        install_projection_schema(driver)
        yield driver


@pytest.fixture
def graph(graph_driver):
    generation = str(uuid4())
    with graph_driver.session() as session:
        session.run(
            "CREATE (:LineScopeGeneration {generation:$generation,validated:true,"
            "snapshot_hash:$hash,validated_at:datetime()})",
            generation=generation,
            hash="0" * 64,
        ).consume()
    try:
        yield graph_driver, generation, Neo4jProjection(graph_driver)
    finally:
        with graph_driver.session() as session:
            session.run(
                "MATCH (n {generation:$generation}) DETACH DELETE n", generation=generation
            ).consume()


def seed_endpoints(graph, payload):
    driver, generation, _ = graph
    state = payload["state"]
    if payload["aggregate_type"] == "DependencyRelation":
        nodes = [
            (state["source_entity_type"], state["source_entity_id"]),
            (state["target_entity_type"], state["target_entity_id"]),
        ]
    else:
        nodes = [
            ("ProductionOperation", state["production_operation_id"]),
            ("Equipment", state["equipment_id"]),
        ]
    with driver.session() as session:
        for kind, identifier in nodes:
            session.run(
                "MERGE (n:LineScopeEntity {generation:$generation,entity_type:$kind,entity_id:$id}) "
                "ON CREATE SET n.active=true,n.entity_version=7",
                generation=generation,
                kind=kind,
                id=identifier,
            ).consume()


def project(graph, payload, *, outbox_id=None, leadership=None):
    _, generation, adapter = graph
    adapter.apply(
        generation=generation,
        outbox_id=outbox_id or uuid4(),
        payload=payload,
        leadership=leadership or TestLeadership(),
    )


def facts(graph):
    driver, generation, _ = graph
    with driver.session() as session:
        edges = session.run(
            "MATCH (s)-[r]->(t) WHERE r.generation=$generation "
            "RETURN s.entity_id AS source,t.entity_id AS target,type(r) AS type,properties(r) AS properties "
            "ORDER BY type,source,target",
            generation=generation,
        ).data()
        markers = session.run(
            "MATCH (m:LineScopeProjectionMarker {generation:$generation}) "
            "RETURN properties(m) AS properties ORDER BY m.aggregate_type,m.aggregate_id",
            generation=generation,
        ).data()
    return edges, markers


@pytest.mark.parametrize(
    "kind,source,target",
    [
        ("DEPENDS_ON", "Equipment", "InfrastructureResource"),
        ("PRECEDES", "Process", "Process"),
        ("SUPPLIES", "InfrastructureResource", "Equipment"),
        ("CONTROLS", "Equipment", "Equipment"),
        ("PRODUCES", "ProductionOperation", "Product"),
        ("CAN_SUBSTITUTE", "Equipment", "Equipment"),
    ],
)
def test_relation_types_project_saved_direction_properties_and_marker(graph, kind, source, target):
    state = relation()
    state.update(
        relation_type=kind,
        source_entity_type=source,
        target_entity_type=target,
        required=kind in {"DEPENDS_ON", "SUPPLIES"},
    )
    payload = build_projection_payload("DependencyRelation", state)
    seed_endpoints(graph, payload)
    delivery = uuid4()
    project(graph, payload, outbox_id=delivery)
    edges, markers = facts(graph)
    assert len(edges) == len(markers) == 1
    edge = edges[0]
    assert (edge["source"], edge["target"], edge["type"]) == (
        state["source_entity_id"],
        state["target_entity_id"],
        kind,
    )
    props = edge["properties"]
    assert props["source_record_id"] == payload["aggregate_id"]
    assert props["source_version"] == payload["aggregate_version"]
    assert props["source_outbox_id"] == str(delivery)
    assert props["active"] is True and props["required"] == state["required"]
    assert props["effective_from"].iso_format().startswith(payload["state"]["effective_from"][:19])
    marker = markers[0]["properties"]
    assert marker["payload_hash"] == projection_payload_hash(payload)
    assert marker["source_version"] == payload["aggregate_version"]
    assert marker["source_outbox_id"] == str(delivery)
    assert not any(key.startswith("_projection") for key in marker)


def test_assignment_uses_direction_and_disable_are_retained(graph):
    state = assignment()
    payload = build_projection_payload("ProductionOperationEquipmentAssignment", state)
    seed_endpoints(graph, payload)
    project(graph, payload)
    edges, _ = facts(graph)
    assert edges[0]["type"] == "USES"
    assert edges[0]["source"] == state["production_operation_id"]
    assert edges[0]["target"] == state["equipment_id"]
    assert "required" not in edges[0]["properties"]
    state.update(active=False, version=state["version"] + 1)
    project(graph, build_projection_payload("ProductionOperationEquipmentAssignment", state))
    edges, markers = facts(graph)
    assert len(edges) == len(markers) == 1 and edges[0]["properties"]["active"] is False


def test_same_and_older_version_do_not_rewrite_edges_or_marker(graph):
    state = relation()
    state["version"] = 3
    payload = build_projection_payload("DependencyRelation", state)
    seed_endpoints(graph, payload)
    project(graph, payload)
    before = facts(graph)
    project(graph, payload)
    state.update(version=2, active=False)
    project(graph, build_projection_payload("DependencyRelation", state))
    assert facts(graph) == before


def test_same_version_different_payload_fails_without_modification(graph):
    payload = build_projection_payload("DependencyRelation", relation())
    seed_endpoints(graph, payload)
    project(graph, payload)
    before = facts(graph)
    changed = deepcopy(payload)
    changed["state"]["active"] = False
    with pytest.raises(ProjectionIntegrityError, match="different Projection payload"):
        project(graph, changed)
    assert facts(graph) == before


def test_endpoint_and_type_replacement_removes_old_edge(graph):
    state = relation()
    payload = build_projection_payload("DependencyRelation", state)
    seed_endpoints(graph, payload)
    project(graph, payload)
    old = facts(graph)
    state.update(
        version=state["version"] + 1,
        target_entity_id=str(uuid4()),
        source_entity_type="InfrastructureResource",
        source_entity_id=str(uuid4()),
        target_entity_type="Equipment",
        relation_type="SUPPLIES",
        required=True,
    )
    changed = build_projection_payload("DependencyRelation", state)
    seed_endpoints(graph, changed)
    project(graph, changed)
    edges, markers = facts(graph)
    assert len(edges) == len(markers) == 1
    assert edges[0]["type"] == "SUPPLIES" and edges[0]["target"] == state["target_entity_id"]
    assert old[0] != edges
    # Old deliveries cannot reconstruct the replaced endpoint/type.
    project(graph, payload)
    assert facts(graph) == (edges, markers)


def test_missing_endpoint_rolls_back_deleted_edge_and_marker(graph):
    state = relation()
    payload = build_projection_payload("DependencyRelation", state)
    seed_endpoints(graph, payload)
    project(graph, payload)
    before = facts(graph)
    state.update(version=state["version"] + 1, target_entity_id=str(uuid4()))
    with pytest.raises(ProjectionIntegrityError, match="endpoint"):
        project(graph, build_projection_payload("DependencyRelation", state))
    assert facts(graph) == before


def test_failure_after_edge_write_rolls_back_edge_and_marker(graph, monkeypatch):
    payload = build_projection_payload("DependencyRelation", relation())
    seed_endpoints(graph, payload)
    project(graph, payload)
    before = facts(graph)
    _, _, adapter = graph
    original = adapter._replace_edge

    def fail(*arguments):
        original(*arguments)
        raise RuntimeError("Injected after edge replacement")

    monkeypatch.setattr(adapter, "_replace_edge", fail)
    changed = deepcopy(payload)
    changed["aggregate_version"] += 1
    changed["state"]["version"] += 1
    changed["state"]["active"] = False
    with pytest.raises(RuntimeError):
        project(graph, changed)
    assert facts(graph) == before


def test_leader_loss_during_edge_write_rolls_back(graph, monkeypatch):
    payload = build_projection_payload("DependencyRelation", relation())
    seed_endpoints(graph, payload)
    _, _, adapter = graph
    original = adapter._replace_edge
    leader = TestLeadership()

    def lose(*arguments):
        original(*arguments)
        leader.alive = False

    monkeypatch.setattr(adapter, "_replace_edge", lose)
    with pytest.raises(GraphLeadershipLost):
        project(graph, payload, leadership=leader)
    assert facts(graph) == ([], [])


@pytest.mark.parametrize("validated", [False, None])
def test_unverified_or_missing_generation_never_creates_marker(graph, validated):
    driver, generation, _ = graph
    with driver.session() as session:
        session.run(
            "MATCH (g:LineScopeGeneration {generation:$generation}) SET g.validated=$value",
            generation=generation,
            value=validated,
        ).consume()
    with pytest.raises(GraphGenerationUnavailable):
        project(graph, build_projection_payload("DependencyRelation", relation()))
    assert facts(graph) == ([], [])


def test_shared_uuid_in_two_aggregate_namespaces_is_not_deleted(graph):
    dep = relation()
    use = assignment()
    use["assignment_id"] = dep["dependency_relation_id"]
    for kind, state in [
        ("DependencyRelation", dep),
        ("ProductionOperationEquipmentAssignment", use),
    ]:
        payload = build_projection_payload(kind, state)
        seed_endpoints(graph, payload)
        project(graph, payload)
    dep.update(version=dep["version"] + 1, active=False)
    project(graph, build_projection_payload("DependencyRelation", dep))
    edges, markers = facts(graph)
    assert len(edges) == len(markers) == 2
    assert next(edge for edge in edges if edge["type"] == "USES")["properties"]["active"] is True


def test_marker_write_lock_serializes_competing_versions(graph, monkeypatch):
    payload = build_projection_payload("DependencyRelation", relation())
    seed_endpoints(graph, payload)
    project(graph, payload)
    driver, generation, first = graph
    second = Neo4jProjection(driver)
    entered, release = Event(), Event()
    original = first._replace_edge

    def hold(*arguments):
        entered.set()
        assert release.wait(5)
        original(*arguments)

    monkeypatch.setattr(first, "_replace_edge", hold)
    newer = deepcopy(payload)
    newer["aggregate_version"] += 2
    newer["state"]["version"] += 2
    older = deepcopy(payload)
    older["aggregate_version"] += 1
    older["state"]["version"] += 1
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(project, graph, newer)
        assert entered.wait(5)
        two = executor.submit(project, (driver, generation, second), older)
        try:
            with pytest.raises(TimeoutError):
                two.result(timeout=0.2)
        finally:
            release.set()
        one.result(timeout=5)
        two.result(timeout=5)
    edges, markers = facts(graph)
    assert len(edges) == len(markers) == 1
    assert markers[0]["properties"]["source_version"] == newer["aggregate_version"]
    assert markers[0]["properties"]["payload_hash"] == projection_payload_hash(newer)


def test_real_neo4j_commit_survives_pg_ack_failure_and_replay_is_idempotent(graph, queued):
    db, _, queue = queued
    _, generation, adapter = graph
    with db.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
            (generation,),
        )
        c.execute(
            "CREATE FUNCTION reject_graph_ack() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'ack fault'; END $$"
        )
        c.execute(
            "CREATE TRIGGER reject_graph_ack BEFORE UPDATE ON graph_outbox FOR EACH ROW WHEN (NEW.status='APPLIED') EXECUTE FUNCTION reject_graph_ack()"
        )
    with graph_leadership(db) as leader:
        event = queue.claim(leader)
        seed_endpoints(graph, event["payload"])
        service = ProjectionApplication(db)
        with pytest.raises(psycopg.Error):
            service.apply(leader, event, adapter)
        before = facts(graph)
        assert len(before[0]) == 1
        with db.transaction() as c:
            assert (
                c.execute(
                    "SELECT status FROM graph_outbox WHERE outbox_id=%s", (event["outbox_id"],)
                ).fetchone()["status"]
                == "PROCESSING"
            )
            c.execute("DROP TRIGGER reject_graph_ack ON graph_outbox")
        assert service.apply(leader, event, adapter)
        assert facts(graph) == before
        with db.transaction() as c:
            assert (
                c.execute(
                    "SELECT status FROM graph_outbox WHERE outbox_id=%s", (event["outbox_id"],)
                ).fetchone()["status"]
                == "APPLIED"
            )


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_invalid_timeout_is_rejected_before_driver_use(timeout):
    with pytest.raises(ValueError):
        Neo4jProjection(None, timeout_seconds=timeout)


def test_composite_marker_constraint_rejects_duplicate_identity(graph):
    payload = build_projection_payload("DependencyRelation", relation())
    seed_endpoints(graph, payload)
    project(graph, payload)
    driver, generation, _ = graph
    before = facts(graph)
    with driver.session() as session, pytest.raises(ConstraintError):
        session.run(
            "CREATE (:LineScopeProjectionMarker {generation:$generation,"
            "aggregate_type:$kind,aggregate_id:$id})",
            generation=generation,
            kind=payload["aggregate_type"],
            id=payload["aggregate_id"],
        ).consume()
    assert facts(graph) == before


@pytest.mark.parametrize(
    "properties",
    [
        {"source_version": 0},
        {"source_version": True},
        {"source_version": 9, "payload_hash": "bad", "source_outbox_id": str(uuid4())},
        {"source_version": 9, "payload_hash": "0" * 64, "source_outbox_id": "invalid"},
    ],
)
def test_invalid_existing_marker_is_not_treated_as_success(graph, properties):
    driver, generation, _ = graph
    payload = build_projection_payload("DependencyRelation", relation())
    with driver.session() as session:
        session.run(
            "CREATE (m:LineScopeProjectionMarker {generation:$generation,"
            "aggregate_type:$kind,aggregate_id:$id}) SET m += $properties",
            generation=generation,
            kind=payload["aggregate_type"],
            id=payload["aggregate_id"],
            properties=properties,
        ).consume()
    before = facts(graph)
    with pytest.raises(ValueError):
        project(graph, payload)
    assert facts(graph) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", "' OR 1=1 --"),
        ("outbox_id", "'; DROP TABLE equipment; --"),
        ("relation_type", "DEPENDS_ON]->() DELETE r //"),
    ],
)
def test_untrusted_identifier_is_rejected_before_driver_access(field, value):
    payload = build_projection_payload("DependencyRelation", relation())
    arguments = dict(
        generation=uuid4(), outbox_id=uuid4(), payload=payload, leadership=TestLeadership()
    )
    if field == "relation_type":
        payload["state"][field] = value
    else:
        arguments[field] = value
    with pytest.raises(ValueError):
        Neo4jProjection(None).apply(**arguments)


def test_other_generation_with_same_aggregate_is_untouched(graph):
    driver, generation, adapter = graph
    other_generation = str(uuid4())
    other = (driver, other_generation, adapter)
    payload = build_projection_payload("DependencyRelation", relation())
    try:
        with driver.session() as session:
            session.run(
                "CREATE (:LineScopeGeneration {generation:$generation,validated:true})",
                generation=other_generation,
            ).consume()
        for target in (graph, other):
            seed_endpoints(target, payload)
            project(target, payload)
        before = facts(other)
        changed = deepcopy(payload)
        changed["aggregate_version"] += 1
        changed["state"]["version"] += 1
        changed["state"]["active"] = False
        project(graph, changed)
        assert facts(other) == before
        assert facts(graph)[0][0]["properties"]["active"] is False
    finally:
        with driver.session() as session:
            session.run(
                "MATCH (n {generation:$generation}) DETACH DELETE n", generation=other_generation
            ).consume()


def test_absent_endpoints_never_create_nodes_or_commit_partial_marker(graph):
    payload = build_projection_payload("DependencyRelation", relation())
    with pytest.raises(ProjectionIntegrityError):
        project(graph, payload)
    assert facts(graph) == ([], [])
    driver, generation, _ = graph
    with driver.session() as session:
        assert (
            session.run(
                "MATCH (n:LineScopeEntity {generation:$generation}) RETURN count(n) AS count",
                generation=generation,
            ).single()["count"]
            == 0
        )


def test_server_timeout_during_marker_lock_rolls_back_without_retries(graph):
    driver, generation, _ = graph
    payload = build_projection_payload("DependencyRelation", relation())
    seed_endpoints(graph, payload)
    project(graph, payload)
    before = facts(graph)
    adapter = Neo4jProjection(driver, timeout_seconds=0.5)
    with driver.session() as session, session.begin_transaction() as holder:
        holder.run(
            "MATCH (m:LineScopeProjectionMarker {generation:$generation}) SET m._test_lock=true",
            generation=generation,
        ).consume()
        with pytest.raises(Neo4jError):
            project((driver, generation, adapter), payload)
        holder.rollback()
    assert facts(graph) == before
