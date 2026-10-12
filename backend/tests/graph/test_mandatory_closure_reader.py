from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from linescope.application.reads import ToolError
from linescope.demo_graph_seed import demo_id
from linescope.domain.graph_fulfillment import structural_fulfillment
from linescope.graph.analysis_budget import GraphAnalysisBudget

AS_OF = datetime(2026, 10, 12, tzinfo=timezone.utc)
P = ("Product", str(demo_id("P-100")))
M = ("Equipment", "20400000-0000-4000-8000-000000000001")
OTHER = ("Equipment", "20800000-0000-4000-8000-000000000001")
RESOURCE = ("InfrastructureResource", str(demo_id("R-02")))


def closure(reader, *, target=P, max_nodes=20, max_depth=16, should_stop=None, as_of=AS_OF):
    with reader.open(GraphAnalysisBudget(5000)) as read:
        result = read.mandatory_closure(
            *target,
            as_of=as_of,
            max_depth=max_depth,
            max_nodes=max_nodes,
            page_size=1,
            should_stop=should_stop,
        )
    return result


def test_all_mandatory_cross_edges_are_preserved_in_verified_read(reader_world):
    reader, generation = reader_world
    result = closure(reader)
    assert result.reachability.complete
    assert len(result.prerequisites) == 7
    assert len(result.edges) == 7  # BFS predecessors alone would have only six.
    assert set(result.prerequisites[P]) == {
        ("Process", str(demo_id("P-20"))),
        ("ProductionOperation", str(demo_id("OP-40"))),
    }
    assert result.prerequisites[M] == (RESOURCE,)
    assert all(edge["relation_type"] != "CAN_SUBSTITUTE" for edge in result.edges)
    assert any(
        edge["relation_type"] == "USES" and edge["required"] is True for edge in result.edges
    )
    assert (
        structural_fulfillment(P, result.prerequisites, complete=True).determination
        == "ESTABLISHED"
    )
    with reader.open(GraphAnalysisBudget(5000)) as read:
        assert read.validation.generation == generation


def modify(reader, query, **params):
    with reader.driver.session() as session:
        session.run(query, **params).consume()


def test_optional_dependency_does_not_consume_semantic_node_budget(reader_world):
    reader, generation = reader_world
    modify(
        reader,
        "MATCH ()-[r:SUPPLIES {generation:$generation}]->(t {entity_id:$id}) SET r.required=false",
        generation=generation,
        id=M[1],
    )
    result = closure(reader, target=M, max_nodes=1)
    assert result.reachability.complete
    assert result.prerequisites == {M: ()}
    assert result.edges == ()


@pytest.mark.parametrize("damage", ["inactive", "end_boundary"])
def test_inactive_or_end_boundary_relation_is_excluded(reader_world, damage):
    reader, generation = reader_world
    assignment = "r.active=false" if damage == "inactive" else "r.effective_to=datetime($as_of)"
    query = "MATCH ()-[r:SUPPLIES {generation:$generation}]->(t {entity_id:$id}) SET " + assignment
    modify(reader, query, generation=generation, id=M[1], as_of=AS_OF.isoformat())
    assert closure(reader, target=M).prerequisites == {M: ()}


def test_required_cycle_back_edges_are_kept_and_not_assumed_established(reader_world):
    reader, generation = reader_world
    for source, target in [(M, OTHER), (OTHER, M)]:
        modify(
            reader,
            "MATCH (s:LineScopeEntity {generation:$generation,entity_id:$source}),"
            "(t:LineScopeEntity {generation:$generation,entity_id:$target}) "
            "CREATE (s)-[:SUPPLIES {generation:$generation,source_record_id:$record,"
            "source_version:1,active:true,required:true,effective_from:datetime($as_of)}]->(t)",
            generation=generation,
            source=source[1],
            target=target[1],
            record=str(uuid4()),
            as_of=AS_OF.isoformat(),
        )
    result = closure(reader, target=M)
    assert result.reachability.complete
    assert OTHER in result.prerequisites[M] and M in result.prerequisites[OTHER]
    assert (
        structural_fulfillment(M, result.prerequisites, complete=True).reason == "MANDATORY_CYCLE"
    )


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"max_nodes": 1}, "NODE_COUNT"),
        ({"max_depth": 1}, "DEPTH"),
        ({"should_stop": lambda: True}, "TIMEOUT"),
    ],
)
def test_truncated_closure_never_claims_complete_source_nodes(reader_world, kwargs, reason):
    result = closure(reader_world[0], **kwargs)
    assert result.reachability.complete is False
    assert result.reachability.limit_reason == reason
    assert structural_fulfillment(P, result.prerequisites, complete=False).reason == "INCOMPLETE"


def test_missing_root_is_rejected(reader_world):
    with pytest.raises(ToolError) as caught:
        closure(reader_world[0], target=("Product", str(uuid4())))
    assert caught.value.code == "TARGET_NOT_FOUND"


def test_naive_as_of_is_rejected_before_traversal(reader_world):
    with pytest.raises(ValueError):
        closure(reader_world[0], as_of=datetime(2026, 10, 12))


@pytest.mark.parametrize("required", [True, False])
def test_depends_on_uses_source_to_target_upstream_direction(reader_world, required):
    reader, generation = reader_world
    identifier = str(uuid4())
    modify(
        reader,
        "MATCH (s:LineScopeEntity {generation:$generation,entity_id:$source}),"
        "(t:LineScopeEntity {generation:$generation,entity_id:$target}) "
        "CREATE (s)-[:DEPENDS_ON {generation:$generation,source_record_id:$record,"
        "source_version:1,active:true,required:$required,effective_from:datetime($as_of)}]->(t)",
        generation=generation,
        source=M[1],
        target=OTHER[1],
        record=identifier,
        required=required,
        as_of=AS_OF.isoformat(),
    )
    result = closure(reader, target=M)
    assert (OTHER in result.prerequisites[M]) is required
    evidence = [edge for edge in result.edges if edge["source_record_id"] == identifier]
    assert bool(evidence) is required
    if required:
        assert evidence[0]["source_id"] == M[1] and evidence[0]["target_id"] == OTHER[1]
