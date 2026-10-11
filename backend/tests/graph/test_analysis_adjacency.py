from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from graph.test_analysis_gate import budget
from graph.test_analysis_reader import built as built
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_rebuild_control import store as store
from linescope.domain.graph_traversal import traversal_types
from linescope.graph.analysis_reader import GraphAnalysisReader


@pytest.fixture
def edges(built):
    db, driver, generation, origin, _ = built
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created = {}
    with driver.session() as session:
        for kind in (
            "DEPENDS_ON",
            "PRECEDES",
            "SUPPLIES",
            "CONTROLS",
            "PRODUCES",
            "CAN_SUBSTITUTE",
            "USES",
        ):
            other, record = str(uuid4()), str(uuid4())
            source_type = (
                "Process"
                if kind in {"PRECEDES", "PRODUCES"}
                else "ProductionOperation"
                if kind == "USES"
                else "Equipment"
            )
            target_type = (
                "Product"
                if kind == "PRODUCES"
                else "Process"
                if kind == "PRECEDES"
                else "Equipment"
            )
            # All relationship identifiers are fixed test-owned names, never external input.
            session.run(
                "MERGE (s:LineScopeEntity {generation:$generation,entity_id:$origin,entity_type:$source_type}) SET s.entity_version=7,s.active=true "
                "CREATE (t:LineScopeEntity {generation:$generation,entity_type:$target_type,entity_id:$other,entity_version:1,active:true}) "
                f"CREATE (s)-[r:{kind}]->(t) SET r=$props",
                generation=generation,
                origin=origin,
                other=other,
                source_type=source_type,
                target_type=target_type,
                props={
                    "generation": generation,
                    "source_record_id": record,
                    "source_version": 1,
                    "required": True,
                    "active": True,
                    "effective_from": at,
                    "effective_to": at + timedelta(days=1),
                },
            ).consume()
            created[kind] = (other, record, source_type, target_type)
    return built, at, created


@pytest.mark.parametrize("direction", ["IMPACT", "UPSTREAM"])
def test_saved_direction_is_not_logical_traversal(edges, direction):
    built, at, created = edges
    db, driver, _, origin, _ = built
    forward, reverse = traversal_types(direction)
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        result = read.neighbors("Equipment", origin, direction=direction, as_of=at, limit=20)
        assert {e["relation_type"] for e in result.edges} == (
            forward & {"DEPENDS_ON", "SUPPLIES", "CONTROLS"}
        )
        assert not result.has_more
        for kind in reverse:
            result = read.neighbors(
                created[kind][3], created[kind][0], direction=direction, as_of=at, limit=20
            )
            assert [e["relation_type"] for e in result.edges] == [kind]
            assert result.edges[0]["source_id"] == origin
            assert result.edges[0]["neighbor_id"] == origin


@pytest.mark.parametrize("offset, count", [(-1, 0), (0, 2), (86400, 0)])
def test_half_open_interval(edges, offset, count):
    built, at, _ = edges
    db, driver, _, origin, _ = built
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        result = read.neighbors(
            "Equipment", origin, direction="IMPACT", as_of=at + timedelta(seconds=offset), limit=20
        )
    assert len(result.edges) == count


def test_limit_detects_unreturned_fact_and_orders_by_typed_id(edges):
    built, at, _ = edges
    db, driver, _, origin, _ = built
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        full = read.neighbors("Equipment", origin, direction="IMPACT", as_of=at, limit=2)
        partial = read.neighbors("Equipment", origin, direction="IMPACT", as_of=at, limit=1)
    assert not full.has_more and partial.has_more
    assert partial.edges == full.edges[:1]
    assert [(e["neighbor_type"], e["neighbor_id"]) for e in full.edges] == sorted(
        (e["neighbor_type"], e["neighbor_id"]) for e in full.edges
    )


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_limit_rejected_before_query(edges, limit):
    built, at, _ = edges
    db, driver, _, origin, _ = built
    with GraphAnalysisReader(db, driver).open(budget()) as read, pytest.raises(ValueError):
        read.neighbors("Equipment", origin, direction="IMPACT", as_of=at, limit=limit)


@pytest.mark.parametrize("direction", ["IMPACT", "UPSTREAM"])
def test_all_relation_directions_with_valid_domain_endpoints(edges, direction):
    built, at, created = edges
    db, driver, _, origin, _ = built
    forward, reverse = traversal_types(direction)
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        for kind, (other, _, source_type, target_type) in created.items():
            start_type, start_id = (
                (source_type, origin) if kind in forward else (target_type, other)
            )
            result = read.neighbors(start_type, start_id, direction=direction, as_of=at, limit=20)
            matches = [e for e in result.edges if e["relation_type"] == kind]
            if kind == "CAN_SUBSTITUTE":
                assert matches == []
            else:
                assert len(matches) == 1
                assert matches[0]["neighbor_id"] == (other if kind in forward else origin)


def test_inactive_relation_is_not_traversed(edges):
    built, at, _ = edges
    db, driver, generation, origin, _ = built
    with driver.session() as session:
        session.run(
            "MATCH ()-[r {generation:$generation}]->() SET r.active=false", generation=generation
        ).consume()
    with GraphAnalysisReader(db, driver).open(budget()) as read:
        assert (
            read.neighbors("Equipment", origin, direction="IMPACT", as_of=at, limit=20).edges == ()
        )
