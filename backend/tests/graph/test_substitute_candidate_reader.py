from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from linescope.application.reads import ToolError
from linescope.graph.analysis_budget import GraphAnalysisBudget

AS_OF = datetime(2026, 10, 12, tzinfo=timezone.utc)
M = "20400000-0000-4000-8000-000000000001"
OTHER = "20800000-0000-4000-8000-000000000001"


def page(reader, *, entity_type="Equipment", entity_id=M, limit=1, after=None, as_of=AS_OF):
    with reader.open(GraphAnalysisBudget(5000)) as read:
        result = read.substitute_candidates(
            entity_type, entity_id, as_of=as_of, limit=limit, after=after
        )
    return result


def mutate(reader, query, **params):
    with reader.driver.session() as session:
        session.run(query, **params).consume()


def test_source_substitutes_target_without_reverse_or_availability_inference(reader_world):
    reader, _ = reader_world
    result = page(reader)
    assert len(result.edges) == 1 and not result.has_more
    edge = result.edges[0]
    assert edge["source_id"] == OTHER and edge["target_id"] == M
    assert edge["neighbor_id"] == OTHER
    assert edge["relation_type"] == "CAN_SUBSTITUTE" and edge["required"] is False
    assert edge["source_version"] == 1
    assert page(reader, entity_id=OTHER).edges == ()


def test_chain_is_not_followed_and_candidate_pages_keep_evidence(reader_world):
    reader, generation = reader_world
    third = str(uuid4())
    with reader.driver.session() as session:
        session.run(
            "CREATE (:LineScopeEntity {generation:$g,entity_type:'Equipment',entity_id:$id,entity_version:1,active:true})",
            g=generation,
            id=third,
        ).consume()
    for target in (M, OTHER):
        mutate(
            reader,
            "MATCH (s:LineScopeEntity {generation:$g,entity_id:$source}),"
            "(t:LineScopeEntity {generation:$g,entity_id:$target}) "
            "CREATE (s)-[:CAN_SUBSTITUTE {generation:$g,source_record_id:$record,"
            "source_version:1,required:false,active:true,effective_from:datetime($as_of)}]->(t)",
            g=generation,
            source=third,
            target=target,
            record=str(uuid4()),
            as_of=AS_OF.isoformat(),
        )
    first = page(reader)
    assert first.has_more and len(first.edges) == 1
    edge = first.edges[-1]
    second = page(
        reader, after=(edge["neighbor_type"], edge["neighbor_id"], edge["source_record_id"])
    )
    assert not second.has_more and len(second.edges) == 1
    assert {first.edges[0]["source_id"], second.edges[0]["source_id"]} == {OTHER, third}
    # Remove third's direct edge to M. Its edge to OTHER must not make it a candidate for M.
    mutate(
        reader,
        "MATCH (s {generation:$g,entity_id:$id})-[r:CAN_SUBSTITUTE]->(t {entity_id:$target}) DELETE r",
        g=generation,
        id=third,
        target=M,
    )
    assert [item["source_id"] for item in page(reader, limit=10).edges] == [OTHER]


@pytest.mark.parametrize(
    "condition",
    [
        "r.active=false",
        "s.active=false",
        "r.effective_to=datetime($as_of)",
        "r.effective_from=datetime($as_of)+duration('PT1H')",
    ],
)
def test_inactive_and_out_of_period_candidates_are_excluded(reader_world, condition):
    reader, generation = reader_world
    mutate(
        reader,
        "MATCH (s)-[r:CAN_SUBSTITUTE {generation:$g}]->() SET " + condition,
        g=generation,
        as_of=AS_OF.isoformat(),
    )
    assert page(reader).edges == ()


@pytest.mark.parametrize(
    "damage",
    [
        "r.required=true",
        "r.source_version=0",
        "r.source_record_id='invalid'",
        "s.entity_type='Process'",
    ],
)
def test_corrupt_relation_is_not_silently_accepted(reader_world, damage):
    reader, generation = reader_world
    mutate(reader, "MATCH (s)-[r:CAN_SUBSTITUTE {generation:$g}]->() SET " + damage, g=generation)
    with pytest.raises(ToolError) as caught:
        page(reader)
    assert caught.value.code == "GRAPH_UNAVAILABLE"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"entity_type": "Product"},
        {"entity_id": "' OR 1=1 --"},
        {"limit": 0},
        {"limit": True},
        {"as_of": datetime(2026, 10, 12)},
        {"after": ("Process", OTHER, str(uuid4()))},
    ],
)
def test_invalid_arguments_are_rejected(reader_world, kwargs):
    with pytest.raises(ValueError):
        page(reader_world[0], **kwargs)


def test_missing_target_is_rejected(reader_world):
    with pytest.raises(ToolError) as caught:
        page(reader_world[0], entity_id=str(uuid4()))
    assert caught.value.code == "TARGET_NOT_FOUND"
