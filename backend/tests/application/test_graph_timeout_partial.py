from contextlib import contextmanager

import pytest
from graph.test_analysis_reader import built as built
from graph.test_analysis_traversal import chain as chain
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_rebuild_control import store as store

from application.test_graph_analysis import context
from application.test_graph_analysis import world as world
from linescope.application.graph_analysis import GraphAnalysis
from linescope.application.graph_request import GraphLimits
from linescope.application.reads import ToolError
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_reader import GraphAnalysisReader
from linescope.graph.analysis_states import GraphStateReader


def timed_service(world, *, expire_at_end=False, rebuild_at_end=False):
    db, driver, _, _, _, _, _, at = world
    clock = [0.0]
    delegate = GraphAnalysisReader(db, driver)
    states = GraphStateReader(db)

    class SlowReader:
        @contextmanager
        def open(self, guard):
            with delegate.open(guard) as read:
                original = read.neighbors
                calls = [0]

                def neighbors(*args, **kwargs):
                    result = original(*args, **kwargs)
                    calls[0] += 1
                    if calls[0] == 2:
                        clock[0] = 4.75
                    return result

                read.neighbors = neighbors
                yield read

    class FinalStates:
        def read(self, identifiers, guard):
            result = states.read(identifiers, guard)
            if expire_at_end:
                clock[0] = 5.0
            if rebuild_at_end:
                with db.transaction() as connection:
                    connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
            return result

    return GraphAnalysis(
        SlowReader(),
        FinalStates(),
        system_limits=GraphLimits(5, 10, 10, 5000),
        budget_factory=lambda ms: GraphAnalysisBudget(ms, clock=lambda: clock[0]),
        clock=lambda: at,
        page_size=1,
        completion_reserve_ms=500,
    )


def call(service, world):
    return service.call(
        context(),
        "trace_downstream_impact",
        {"target": {"entity_type": "Equipment", "entity_id": world[2]}},
    )


def test_timeout_partial_is_only_confirmed_prefix_with_finished_evidence(world):
    result = call(timed_service(world), world)
    assert not result.data["complete"] and result.data["limit_reason"] == "TIMEOUT"
    assert result.data["reached_nodes"] == [{"entity_type": "Process", "entity_id": world[3]}]
    assert result.data["representative_paths"][0]["hops"] == 1
    assert result.evidence["state_versions"] == {"Equipment:" + world[2]: 3}
    assert world[6] not in str(result.evidence)


def test_partial_is_discarded_when_total_budget_expires_during_finalization(world):
    with pytest.raises(ToolError) as caught:
        call(timed_service(world, expire_at_end=True), world)
    assert caught.value.code == "RESOURCE_BUSY"


def test_partial_is_discarded_when_current_gate_fails(world):
    with pytest.raises(ToolError) as caught:
        call(timed_service(world, rebuild_at_end=True), world)
    assert caught.value.code == "GRAPH_REBUILDING"


@pytest.mark.parametrize("reserve", [0, -1, True, 5000, 6000, float("nan"), float("inf")])
def test_invalid_server_reserve_is_rejected(world, reserve):
    with pytest.raises(ValueError):
        GraphAnalysis(
            None,
            None,
            system_limits=GraphLimits(5, 10, 10, 5000),
            budget_factory=GraphAnalysisBudget,
            completion_reserve_ms=reserve,
        )
