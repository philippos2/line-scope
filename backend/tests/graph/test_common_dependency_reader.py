from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_rebuild_controller import adapters as adapters
from linescope.application.reads import ToolError
from linescope.demo_graph_seed import demo_id, seed_graph_demo
from linescope.domain.graph_common_dependencies import common_dependencies
from linescope.graph.administration import GraphAdministration
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_reader import GraphAnalysisReader

AS_OF = datetime(2026, 10, 12, tzinfo=timezone.utc)
TARGETS = [("Product", str(demo_id(code))) for code in ("P-100", "P-200")]


@pytest.fixture
def reader_world(db, adapters):
    db.migrate()
    seed_graph_demo(db)
    generation = GraphAdministration(db, adapters[1].driver).rebuild().generation
    return GraphAnalysisReader(db, adapters[1].driver), generation


def read_searches(reader, targets=TARGETS, *, max_nodes=8, should_stop=None):
    with reader.open(GraphAnalysisBudget(5000)) as read:
        generation = read.validation.generation
        searches = read.common_dependency_searches(
            targets,
            as_of=AS_OF,
            max_depth=16,
            max_nodes=max_nodes,
            page_size=2,
            should_stop=should_stop,
        )
    return searches, generation


def test_real_common_paths_share_verified_generation_and_all_source_facts(reader_world):
    reader, expected_generation = reader_world
    searches, generation = read_searches(reader)
    assert generation == expected_generation
    selected = common_dependencies(
        [(target, result.reachability) for target, result in searches], max_paths=12
    )
    assert selected.complete and len(selected.candidates) == 6
    assert all(len(candidate.paths) == 2 for candidate in selected.candidates)
    for candidate in selected.candidates:
        for item in candidate.paths:
            traversal = dict(searches)[item.target]
            facts = {edge["source_record_id"] for edge in traversal.edges}
            assert set(item.path.source_record_ids) <= facts
            assert item.path.nodes[0] == item.target and item.path.nodes[-1] == candidate.candidate
    reversed_searches, _ = read_searches(reader, list(reversed(TARGETS)))
    assert reversed_searches == searches


def test_distinct_nodes_are_bounded_across_all_targets(reader_world):
    searches, _ = read_searches(reader_world[0], max_nodes=5)
    union = {item.node for _, result in searches for item in result.reachability.nodes}
    assert len(union) == 5
    selected = common_dependencies(
        [(target, result.reachability) for target, result in searches], max_paths=12
    )
    assert not selected.complete and selected.limit_reason == "NODE_COUNT"
    assert all(len(candidate.paths) == 2 for candidate in selected.candidates)


def test_output_path_budget_is_applied_after_shared_upstream_reads(reader_world):
    searches, _ = read_searches(reader_world[0])
    selected = common_dependencies(
        [(target, result.reachability) for target, result in searches], max_paths=1
    )
    assert not selected.complete and selected.limit_reason == "PATH_COUNT"
    assert selected.candidates == ()


def test_missing_target_rejects_entire_multi_target_read(reader_world):
    with pytest.raises(ToolError) as error:
        read_searches(reader_world[0], [TARGETS[0], ("Product", str(uuid4()))])
    assert error.value.code == "TARGET_NOT_FOUND"


def test_soft_deadline_preserves_incomplete_searches_inside_gate(reader_world):
    searches, _ = read_searches(reader_world[0], should_stop=lambda: True)
    selected = common_dependencies(
        [(target, result.reachability) for target, result in searches], max_paths=12
    )
    assert selected.candidates == () and not selected.complete
    assert selected.limit_reason == "TIMEOUT"


def test_budget_must_hold_all_target_roots(reader_world):
    with pytest.raises(ValueError, match="all targets"):
        read_searches(reader_world[0], max_nodes=1)
