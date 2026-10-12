from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from linescope.demo_graph_seed import demo_id
from linescope.domain.graph_reachability import TraversalNodeBudget
from linescope.domain.graph_substitute_selection import select_substitutes_for_exclusion
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.substitute_facts import collect_substitute_facts

AS_OF = datetime(2026, 10, 12, tzinfo=timezone.utc)
M = ("Equipment", "20400000-0000-4000-8000-000000000001")
OTHER = ("Equipment", "20800000-0000-4000-8000-000000000001")
RESOURCE = ("InfrastructureResource", str(demo_id("R-02")))


def collect(reader, *, max_nodes=3, should_stop=None, node_budget=None, target=M):
    with reader.open(GraphAnalysisBudget(5000)) as read:
        result = collect_substitute_facts(
            read,
            target,
            as_of=AS_OF,
            max_depth=16,
            max_nodes=max_nodes,
            page_size=1,
            should_stop=should_stop,
            node_budget=node_budget,
        )
    return result


def test_original_candidate_and_prerequisites_share_budget_and_feed_evaluator(reader_world):
    result = collect(reader_world[0])
    assert result.complete and result.limit_reason is None
    assert result.candidates == (OTHER,)
    assert result.prerequisites == {M: (RESOURCE,), RESOURCE: (), OTHER: ()}
    assert len(result.dependency_edges) == 1 and len(result.substitution_edges) == 1
    assert {
        node for _, search in result.searches for node in (item.node for item in search.nodes)
    } == {M, OTHER, RESOURCE}
    evaluated = select_substitutes_for_exclusion(
        M,
        list(result.candidates),
        result.prerequisites,
        {OTHER: "AVAILABLE"},
        complete=result.complete,
        historical=False,
    )
    assert evaluated.availability == "AVAILABLE"


@pytest.mark.parametrize("max_nodes", [1, 2])
def test_candidate_admission_cannot_reset_original_closure_budget(reader_world, max_nodes):
    result = collect(reader_world[0], max_nodes=max_nodes)
    assert result.complete is False and result.limit_reason == "NODE_COUNT"
    assert result.candidates == ()
    nodes = {item.node for _, search in result.searches for item in search.nodes}
    assert len(nodes) <= max_nodes
    assert len(result.prerequisites) <= max_nodes
    assert all(set(upstream) <= nodes for upstream in result.prerequisites.values())


def test_budget_can_be_shared_with_prior_target_search(reader_world):
    budget = TraversalNodeBudget(3, roots=(M, RESOURCE))
    result = collect(reader_world[0], node_budget=budget)
    assert result.complete and budget.nodes == {M, RESOURCE, OTHER}


def test_soft_deadline_does_not_prove_empty_candidates(reader_world):
    result = collect(reader_world[0], should_stop=lambda: True)
    assert result.candidates == () and not result.complete and result.limit_reason == "TIMEOUT"


def test_fully_searched_empty_set_is_complete(reader_world):
    result = collect(reader_world[0], target=OTHER)
    assert result.complete and result.candidates == ()


def test_candidate_dependencies_on_original_are_preserved_not_replaced(reader_world):
    reader, generation = reader_world
    with reader.driver.session() as session:
        session.run(
            "MATCH (s:LineScopeEntity {generation:$g,entity_id:$source}),"
            "(t:LineScopeEntity {generation:$g,entity_id:$target}) "
            "CREATE (s)-[:DEPENDS_ON {generation:$g,source_record_id:$record,"
            "source_version:1,required:true,active:true,effective_from:datetime($as_of)}]->(t)",
            g=generation,
            source=OTHER[1],
            target=M[1],
            record=str(uuid4()),
            as_of=AS_OF.isoformat(),
        ).consume()
    result = collect(reader)
    assert result.complete and result.prerequisites[OTHER] == (M,)
    evaluation = select_substitutes_for_exclusion(
        M,
        list(result.candidates),
        result.prerequisites,
        {M: "AVAILABLE", OTHER: "AVAILABLE"},
        complete=result.complete,
        historical=False,
    )
    assert evaluation.availability == "UNAVAILABLE"


@pytest.mark.parametrize(
    "budget",
    [
        TraversalNodeBudget(2, roots=(M,)),
        TraversalNodeBudget(
            3,
            roots=(("Product", str(uuid4())), ("Product", str(uuid4())), ("Product", str(uuid4()))),
        ),
    ],
)
def test_inconsistent_or_full_external_budget_is_rejected(reader_world, budget):
    with pytest.raises(ValueError):
        collect(reader_world[0], node_budget=budget)


def test_candidate_closure_cannot_reset_budget(reader_world):
    reader, generation = reader_world
    process = ("Process", str(demo_id("P-10")))
    with reader.driver.session() as session:
        session.run(
            "MATCH (s:LineScopeEntity {generation:$g,entity_id:$source}),"
            "(t:LineScopeEntity {generation:$g,entity_id:$target}) "
            "CREATE (s)-[:DEPENDS_ON {generation:$g,source_record_id:$record,"
            "source_version:1,required:true,active:true,effective_from:datetime($as_of)}]->(t)",
            g=generation,
            source=OTHER[1],
            target=process[1],
            record=str(uuid4()),
            as_of=AS_OF.isoformat(),
        ).consume()
    result = collect(reader)
    assert result.candidates == (OTHER,) and result.limit_reason == "NODE_COUNT"
    assert not result.complete and len(result.prerequisites) <= 3
    evaluation = select_substitutes_for_exclusion(
        M,
        list(result.candidates),
        result.prerequisites,
        {OTHER: "AVAILABLE"},
        complete=result.complete,
        historical=False,
    )
    assert evaluation.availability == "UNKNOWN"


def test_parallel_candidate_records_keep_evidence_without_repeated_closure(reader_world):
    reader, generation = reader_world
    with reader.driver.session() as session:
        session.run(
            "MATCH (s:LineScopeEntity {generation:$g,entity_id:$source}),"
            "(t:LineScopeEntity {generation:$g,entity_id:$target}) "
            "CREATE (s)-[:CAN_SUBSTITUTE {generation:$g,source_record_id:$record,"
            "source_version:2,required:false,active:true,effective_from:datetime($as_of)}]->(t)",
            g=generation,
            source=OTHER[1],
            target=M[1],
            record=str(uuid4()),
            as_of=AS_OF.isoformat(),
        ).consume()
    result = collect(reader)
    assert result.complete and result.candidates == (OTHER,)
    assert len(result.substitution_edges) == 2
    assert len(result.searches) == 2
