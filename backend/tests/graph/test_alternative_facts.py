from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from linescope.application.reads import ToolError
from linescope.demo_graph_seed import demo_id
from linescope.graph.alternative_facts import collect_alternative_facts
from linescope.graph.analysis_budget import GraphAnalysisBudget

AS_OF = datetime(2026, 10, 13, tzinfo=timezone.utc)
P = ("Product", str(demo_id("P-100")))
Q = ("Product", str(demo_id("P-200")))
M = ("Equipment", "20400000-0000-4000-8000-000000000001")
OTHER = ("Equipment", "20800000-0000-4000-8000-000000000001")
OP = ("ProductionOperation", str(demo_id("OP-30")))


def collect(reader, *, targets=(P, Q), excluded=(M,), max_nodes=9, max_depth=16, should_stop=None):
    with reader.open(GraphAnalysisBudget(5000)) as read:
        result = collect_alternative_facts(
            read,
            targets,
            excluded,
            as_of=AS_OF,
            max_depth=max_depth,
            max_nodes=max_nodes,
            page_size=1,
            should_stop=should_stop,
        )
    return result


def test_all_targets_exclusions_and_candidates_share_one_budget(reader_world):
    reader, _ = reader_world
    result = collect(reader)
    assert result.complete and len(result.prerequisites) == 9
    assert len(result.dependency_edges) == 9
    assert result.important_targets == (P, Q)
    assert result.substitutes[0].candidates == (OTHER,)
    assert result.substitutes[0].prerequisites == result.prerequisites
    assert result == collect(reader, targets=(Q, P))


def test_candidate_admission_cannot_reset_multi_target_budget(reader_world):
    result = collect(reader_world[0], max_nodes=8)
    assert not result.complete and result.limit_reason == "NODE_COUNT"
    assert len(result.prerequisites) <= 8
    assert result.substitutes[0].candidates == ()
    assert not result.substitutes[0].complete


def test_all_exclusions_seed_global_budget_and_are_retained(reader_world):
    result = collect(reader_world[0], excluded=(OTHER, M))
    assert result.complete and result.excluded_nodes == (M, OTHER)
    assert {item.target for item in result.substitutes} == {M, OTHER}
    assert all(item.prerequisites == result.prerequisites for item in result.substitutes)


def test_non_substitutable_operation_keeps_closure_without_substitute_query(reader_world):
    result = collect(reader_world[0], excluded=(OP,))
    assert result.complete and result.substitutes[0].target == OP
    assert result.substitutes[0].candidates == () and result.substitutes[0].substitution_edges == ()
    assert M in result.prerequisites[OP]


def test_missing_exclusion_rejects_entire_read(reader_world):
    with pytest.raises(ToolError) as caught:
        collect(reader_world[0], excluded=(M, ("Equipment", str(uuid4()))))
    assert caught.value.code == "TARGET_NOT_FOUND"


def test_inactive_input_rejects_entire_read(reader_world):
    reader, generation = reader_world
    with reader.driver.session() as session:
        session.run(
            "MATCH (n {generation:$g,entity_id:$id}) SET n.active=false", g=generation, id=OTHER[1]
        ).consume()
    with pytest.raises(ToolError) as caught:
        collect(reader, excluded=(OTHER,))
    assert caught.value.code == "TARGET_NOT_FOUND"


def test_overlap_between_target_and_exclusion_counts_once(reader_world):
    result = collect(reader_world[0], targets=(OTHER,), excluded=(OTHER,), max_nodes=1)
    assert result.complete and len(result.prerequisites) == 1


@pytest.mark.parametrize(
    "kwargs,reason", [({"max_depth": 1}, "DEPTH"), ({"should_stop": lambda: True}, "TIMEOUT")]
)
def test_incomplete_search_applies_to_all_substitute_evaluations(reader_world, kwargs, reason):
    result = collect(reader_world[0], **kwargs)
    assert not result.complete and result.limit_reason == reason
    assert all(not item.complete and item.limit_reason == reason for item in result.substitutes)


def test_root_set_must_fit_before_graph_reads(reader_world):
    with pytest.raises(ValueError):
        collect(reader_world[0], max_nodes=2)


@pytest.mark.parametrize(
    "targets,excluded,max_nodes",
    [
        ((P, Q), (M,), 2),
        ((P, P), (M,), 9),
        ((), (M,), 9),
        ((P,), (), 9),
        ((("SQL", M[1]),), (M,), 9),
    ],
)
def test_invalid_input_sets_fail_before_any_node_lookup(targets, excluded, max_nodes):
    class NoRead:
        def node(self, *args):
            pytest.fail("Invalid input must not perform Graph node reads")

    with pytest.raises(ValueError):
        collect_alternative_facts(
            NoRead(),
            targets,
            excluded,
            as_of=AS_OF,
            max_depth=16,
            max_nodes=max_nodes,
            page_size=1,
        )
