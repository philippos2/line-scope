from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graph.test_analysis_gate import budget
from graph.test_analysis_reader import built as built
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_rebuild_control import store as store
from linescope.application.reads import ToolError
from linescope.graph.analysis_reader import GraphAnalysisReader


@pytest.fixture
def chain(built):
    db, driver, generation, origin, _ = built
    process, product, first, second = [str(uuid4()) for _ in range(4)]
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with driver.session() as session:
        session.run(
            "MATCH (s:LineScopeEntity {generation:$generation,entity_type:'Equipment',entity_id:$origin}) "
            "CREATE (p:LineScopeEntity {generation:$generation,entity_type:'Process',entity_id:$process,entity_version:1,active:true}) "
            "CREATE (t:LineScopeEntity {generation:$generation,entity_type:'Product',entity_id:$product,entity_version:1,active:true}) "
            "CREATE (s)-[a:SUPPLIES]->(p) SET a=$first "
            "CREATE (p)-[b:PRODUCES]->(t) SET b=$second",
            generation=generation,
            origin=origin,
            process=process,
            product=product,
            first={
                "generation": generation,
                "source_record_id": first,
                "source_version": 1,
                "required": False,
                "active": True,
                "effective_from": at,
            },
            second={
                "generation": generation,
                "source_record_id": second,
                "source_version": 1,
                "required": False,
                "active": True,
                "effective_from": at,
            },
        ).consume()
    return db, driver, origin, process, product, first, second, at


def traverse(chain, *, direction="IMPACT", **limits):
    db, driver, origin, _, product, _, _, at = chain
    root = ("Equipment", origin) if direction == "IMPACT" else ("Product", product)
    with GraphAnalysisReader(db, driver).open(budget(5)) as read:
        return read.traverse(
            *root,
            direction=direction,
            as_of=at,
            max_depth=limits.get("max_depth", 5),
            max_nodes=limits.get("max_nodes", 10),
            max_paths=limits.get("max_paths", 10),
            page_size=limits.get("page_size", 1),
        )


@pytest.mark.parametrize("direction", ["IMPACT", "UPSTREAM"])
def test_multihop_paths_and_evidence_keep_saved_direction(chain, direction):
    _, _, origin, process, product, first, second, _ = chain
    result = traverse(chain, direction=direction)
    nodes = (("Equipment", origin), ("Process", process), ("Product", product))
    records = (first, second)
    if direction == "UPSTREAM":
        nodes, records = tuple(reversed(nodes)), tuple(reversed(records))
    assert [item.distance for item in result.reachability.nodes] == [0, 1, 2]
    assert result.paths.paths[-1].nodes == nodes
    assert result.paths.paths[-1].source_record_ids == records
    assert result.paths.complete
    assert {item["source_record_id"] for item in result.edges} == {first, second}
    facts = {item["source_record_id"]: item for item in result.edges}
    assert facts[first]["source_id"] == origin and facts[first]["target_id"] == process
    assert facts[second]["source_id"] == process and facts[second]["target_id"] == product


@pytest.mark.parametrize(
    "limits,reason",
    [
        ({"max_depth": 1}, "DEPTH"),
        ({"max_nodes": 2}, "NODE_COUNT"),
        ({"max_paths": 1}, "PATH_COUNT"),
    ],
)
def test_limits_only_return_evidence_for_returned_paths(chain, limits, reason):
    result = traverse(chain, **limits)
    assert result.paths.limit_reason == reason and not result.paths.complete
    assert len(result.paths.paths) == 1 and len(result.edges) == 1
    assert len(result.reachability.nodes) == (3 if reason == "PATH_COUNT" else 2)


def test_exact_limits_are_complete(chain):
    result = traverse(chain, max_depth=2, max_nodes=3, max_paths=2)
    assert result.paths.complete and result.paths.limit_reason is None


def test_page_sizes_produce_identical_results(chain):
    db, driver, origin, _, _, _, _, at = chain
    extra, record = str(uuid4()), str(uuid4())
    with driver.session() as session:
        session.run(
            "MATCH (s:LineScopeEntity {entity_type:'Equipment',entity_id:$origin}) "
            "CREATE (t:LineScopeEntity {entity_type:'Equipment',entity_id:$extra,entity_version:1,active:true}) "
            "SET t.generation=s.generation "
            "CREATE (s)-[r:SUPPLIES]->(t) SET r=$props,r.generation=s.generation",
            origin=origin,
            extra=extra,
            props={
                "source_record_id": record,
                "source_version": 1,
                "required": False,
                "active": True,
                "effective_from": at,
            },
        ).consume()
    assert traverse(chain, page_size=1) == traverse(chain, page_size=20)
    result = traverse(chain)
    assert len(result.reachability.nodes) == 4 and result.paths.complete
    assert any(item.node == ("Equipment", extra) for item in result.reachability.nodes)


def test_end_gate_still_discards_traversal(chain):
    db, driver, origin, _, _, _, _, at = chain
    with (
        pytest.raises(ToolError) as caught,
        GraphAnalysisReader(db, driver).open(budget(5)) as read,
    ):
        read.traverse(
            "Equipment",
            origin,
            direction="IMPACT",
            as_of=at,
            max_depth=5,
            max_nodes=10,
            max_paths=10,
            page_size=1,
        )
        with db.transaction() as connection:
            connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
    assert caught.value.code == "GRAPH_REBUILDING"


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_inactive_root_is_not_an_empty_success(chain, missing):
    db, driver, origin, _, _, _, _, at = chain
    if missing:
        origin = str(uuid4())
    else:
        with driver.session() as session:
            session.run(
                "MATCH (n:LineScopeEntity {entity_type:'Equipment',entity_id:$origin}) SET n.active=false",
                origin=origin,
            ).consume()
    with (
        pytest.raises(ToolError) as caught,
        GraphAnalysisReader(db, driver).open(budget(5)) as read,
    ):
        read.traverse(
            "Equipment",
            origin,
            direction="IMPACT",
            as_of=at,
            max_depth=5,
            max_nodes=10,
            max_paths=10,
            page_size=1,
        )
    assert caught.value.code == "TARGET_NOT_FOUND"
