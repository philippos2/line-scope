from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from graph.test_analysis_gate import budget
from graph.test_analysis_reader import built as built
from graph.test_analysis_traversal import chain as chain
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_rebuild_control import store as store

from linescope.application.graph_analysis import GraphAnalysis
from linescope.application.graph_request import GraphLimits
from linescope.application.reads import ToolError
from linescope.execution import ExecutionContext
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_reader import GraphAnalysisReader
from linescope.graph.analysis_states import GraphStateReader


def context(role="maintenance"):
    return ExecutionContext("actor", role, uuid4())


def service(chain, *, states=None, reader=None):
    db, driver, _, _, _, _, _, at = chain
    return GraphAnalysis(
        reader or GraphAnalysisReader(db, driver),
        states or GraphStateReader(db),
        system_limits=GraphLimits(5, 10, 10, 5000),
        budget_factory=GraphAnalysisBudget,
        clock=lambda: at,
        page_size=1,
    )


@pytest.fixture
def world(chain):
    db, _, origin, _, _, _, _, _ = chain
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'M-204','Demo','machine',true)",
            (UUID(origin),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code,version) VALUES(%s,'STOPPED',3)",
            (UUID(origin),),
        )
    return chain


@pytest.mark.parametrize("tool", ["trace_downstream_impact", "trace_upstream_dependencies"])
def test_real_graph_and_state_form_server_evidence(world, tool):
    _, _, origin, process, product, _, _, _ = world
    target = (
        {"entity_type": "Equipment", "entity_id": origin}
        if tool == "trace_downstream_impact"
        else {"entity_type": "Product", "entity_id": product}
    )
    result = service(world).call(context(), tool, {"target": target})
    assert result.data["complete"] and len(result.data["reached_nodes"]) == 2
    assert len(result.data["direct_nodes"]) == len(result.data["indirect_nodes"]) == 1
    assert result.data["distances"][target["entity_type"] + ":" + target["entity_id"]] == 0
    assert result.evidence["state_versions"] == {"Equipment:" + origin: 3}
    assert result.evidence["current_states"] == [
        {"equipment_id": origin, "version": 3, "state_code": "STOPPED"}
    ]
    assert result.evidence["missing_states"] == []
    path = result.data["representative_paths"][-1]
    assert path["hops"] == 2 and path == result.evidence["representative_paths"][-1]
    assert path["edges"][0]["source"]["entity_id"] == (
        origin if tool == "trace_downstream_impact" else process
    )
    assert result.evidence["graph_generation"] and result.evidence["state_observed_at"]


def test_relation_filter_is_applied_to_actual_graph(world):
    _, _, origin, process, _, _, _, _ = world
    result = service(world).call(
        context(),
        "trace_downstream_impact",
        {
            "target": {"entity_type": "Equipment", "entity_id": origin},
            "relation_types": ["SUPPLIES"],
        },
    )
    assert result.data["reached_nodes"] == [{"entity_type": "Process", "entity_id": process}]
    assert result.evidence["relation_types"] == ["SUPPLIES"] and result.data["complete"]


def test_partial_paths_do_not_expose_omitted_edge_evidence(world):
    _, _, origin, _, _, first, second, _ = world
    result = service(world).call(
        context(),
        "trace_downstream_impact",
        {"target": {"entity_type": "Equipment", "entity_id": origin}, "requested_max_paths": 1},
    )
    assert not result.data["complete"] and result.data["limit_reason"] == "PATH_COUNT"
    assert {
        edge["source_record_id"]
        for path in result.evidence["representative_paths"]
        for edge in path["edges"]
    } == {first}
    assert second not in str(result.evidence)


def test_missing_state_is_reported_without_zero_or_invented_state(chain):
    _, _, origin, _, _, _, _, _ = chain
    result = service(chain).call(
        context(),
        "trace_downstream_impact",
        {"target": {"entity_type": "Equipment", "entity_id": origin}},
    )
    assert result.evidence["state_versions"] == {} and result.evidence["current_states"] == []
    assert result.evidence["missing_states"] == [origin]


def test_end_gate_discards_result_after_state_observation(world):
    db, _, origin, _, _, _, _, _ = world
    delegate = GraphStateReader(db)

    class ChangingState:
        def read(self, identifiers, guard):
            result = delegate.read(identifiers, guard)
            with db.transaction() as connection:
                connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
            return result

    with pytest.raises(ToolError) as caught:
        service(world, states=ChangingState()).call(
            context(),
            "trace_downstream_impact",
            {"target": {"entity_type": "Equipment", "entity_id": origin}},
        )
    assert caught.value.code == "GRAPH_REBUILDING"


class NeverOpen:
    def open(self, *args):
        raise AssertionError("Storage must not be opened")

    def read(self, *args):
        raise AssertionError("State must not be read")


def test_unauthorized_request_never_opens_storage(chain):
    with pytest.raises(ToolError) as caught:
        service(chain, reader=NeverOpen(), states=NeverOpen()).call(
            context("floor"), "trace_downstream_impact", {}
        )
    assert caught.value.code == "AUTHORIZATION_DENIED"


def test_future_request_never_opens_storage(chain):
    _, _, origin, _, _, _, _, at = chain
    with pytest.raises(ToolError) as caught:
        service(chain, reader=NeverOpen(), states=NeverOpen()).call(
            context(),
            "trace_downstream_impact",
            {
                "target": {"entity_type": "Equipment", "entity_id": origin},
                "explicit_as_of": (at + timedelta(seconds=1)).isoformat(),
            },
        )
    assert caught.value.code == "INVALID_ARGUMENT"


def test_state_reader_returns_timestamp_for_empty_equipment_set(chain):
    db, *_ = chain
    result = GraphStateReader(db).read([], budget(5))
    assert result["states"] is None and result["observed_at"].tzinfo is not None


def test_historical_scope_does_not_claim_historical_equipment_state(world):
    _, _, origin, _, _, _, _, at = world
    result = service(world).call(
        context(),
        "trace_downstream_impact",
        {
            "target": {"entity_type": "Equipment", "entity_id": origin},
            "explicit_as_of": (at - timedelta(seconds=1)).isoformat(),
        },
    )
    assert result.data["reached_nodes"] == [] and result.data["complete"]
    assert result.evidence["temporal_scope"] == "CURRENT_REGISTRATION_AT_AS_OF"
    assert result.evidence["state_temporal_scope"] == "CURRENT_STATE_AT_OBSERVATION"
    assert result.evidence["state_versions"] == {"Equipment:" + origin: 3}
