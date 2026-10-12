from datetime import timedelta
from uuid import uuid4

import pytest
from graph.test_common_dependency_reader import AS_OF, TARGETS
from graph.test_common_dependency_reader import reader_world as reader_world
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_rebuild_controller import adapters as adapters

from application.test_graph_analysis import context
from linescope.application.graph_analysis import GraphAnalysis
from linescope.application.graph_request import GraphLimits, validate_common_dependency_request
from linescope.application.reads import ToolError
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_states import GraphStateReader


def arguments(**extra):
    return {
        "targets": [{"entity_type": kind, "entity_id": identifier} for kind, identifier in TARGETS],
        **extra,
    }


def service(db, reader_world):
    return GraphAnalysis(
        reader_world[0],
        GraphStateReader(db),
        system_limits=GraphLimits(16, 20, 20, 5000),
        budget_factory=GraphAnalysisBudget,
        clock=lambda: AS_OF,
    )


def test_common_candidates_have_all_target_paths_and_current_state_evidence(db, reader_world):
    result = service(db, reader_world).call(context(), "find_common_dependencies", arguments())
    assert result.data["complete"] and len(result.data["common_candidates"]) == 6
    assert len(result.data["representative_paths"]) == 12
    assert result.evidence["graph_generation"] == reader_world[1]
    assert result.evidence["representative_paths"] == result.data["representative_paths"]
    assert result.evidence["state_versions"] == {
        "Equipment:20400000-0000-4000-8000-000000000001": 1
    }
    for candidate in result.data["common_candidates"]:
        paths = [
            path for path in result.data["representative_paths"] if path["candidate"] == candidate
        ]
        assert {path["target"]["entity_id"] for path in paths} == {
            identifier for _, identifier in TARGETS
        }
        assert all(
            path["nodes"][0] == path["target"] and path["nodes"][-1] == candidate for path in paths
        )
    assert "SAFETY" in result.data["not_evaluated"] and result.data["determination"] is None


@pytest.mark.parametrize(
    "limit,reason", [("requested_max_paths", "PATH_COUNT"), ("requested_max_nodes", "NODE_COUNT")]
)
def test_global_limits_preserve_common_search_incompleteness(db, reader_world, limit, reason):
    result = service(db, reader_world).call(
        context(),
        "find_common_dependencies",
        arguments(**{limit: 1 if reason == "PATH_COUNT" else 5}),
    )
    assert not result.data["complete"] and result.data["limit_reason"] == reason
    assert len(result.data["representative_paths"]) == 2 * len(result.data["common_candidates"])


@pytest.mark.parametrize(
    "fault",
    [
        "single",
        "duplicate",
        "case_duplicate",
        "budget",
        "future",
        "substitute",
        "timeout",
        "role",
        "target_extra",
        "bad_id",
    ],
)
def test_invalid_common_requests_are_rejected_before_storage(fault):
    args = arguments()
    if fault == "single":
        args["targets"].pop()
    elif fault == "duplicate":
        args["targets"][1] = args["targets"][0]
    elif fault == "case_duplicate":
        args["targets"][1] = {
            **args["targets"][0],
            "entity_id": args["targets"][0]["entity_id"].upper(),
        }
    elif fault == "budget":
        args["requested_max_nodes"] = 1
    elif fault == "future":
        args["explicit_as_of"] = (AS_OF + timedelta(seconds=1)).isoformat()
    elif fault == "substitute":
        args["relation_types"] = ["CAN_SUBSTITUTE"]
    elif fault == "timeout":
        args["timeout_ms"] = 100000
    elif fault == "role":
        args["role"] = "manager"
    elif fault == "target_extra":
        args["targets"][0]["role"] = "manager"
    else:
        args["targets"][0]["entity_id"] = "' OR 1=1 --"

    class NoReader:
        def open(self, budget):
            raise AssertionError("Storage must not be opened")

    graph = GraphAnalysis(
        NoReader(),
        None,
        system_limits=GraphLimits(16, 20, 20, 5000),
        budget_factory=GraphAnalysisBudget,
        clock=lambda: AS_OF,
    )
    with pytest.raises(ToolError) as error:
        graph.call(context(), "find_common_dependencies", args)
    assert error.value.code == "INVALID_ARGUMENT"


def test_common_authorization_precedes_untrusted_input():
    with pytest.raises(ToolError) as error:
        validate_common_dependency_request(
            context("floor"),
            {"role": "manager"},
            system_limits=GraphLimits(16, 20, 20, 5000),
            server_time=AS_OF,
        )
    assert error.value.code == "AUTHORIZATION_DENIED"


def test_missing_target_rejects_whole_common_request(db, reader_world):
    args = arguments()
    args["targets"][1]["entity_id"] = str(uuid4())
    with pytest.raises(ToolError) as error:
        service(db, reader_world).call(context(), "find_common_dependencies", args)
    assert error.value.code == "TARGET_NOT_FOUND"


def test_inactive_target_rejects_whole_common_request(db, reader_world, adapters):
    from linescope.graph.administration import GraphAdministration

    with db.transaction() as connection:
        connection.execute("UPDATE product SET active=false WHERE product_id=%s", (TARGETS[1][1],))
    GraphAdministration(db, adapters[1].driver).rebuild()
    with pytest.raises(ToolError) as error:
        service(db, reader_world).call(context(), "find_common_dependencies", arguments())
    assert error.value.code == "TARGET_NOT_FOUND"


def test_common_historical_filter_keeps_current_state_observation(db, reader_world):
    result = service(db, reader_world).call(
        context(),
        "find_common_dependencies",
        arguments(explicit_as_of=(AS_OF - timedelta(days=1)).isoformat()),
    )
    assert result.data["analysis_mode"] == "EXPLICIT_HISTORICAL"
    assert result.evidence["temporal_scope"] == "CURRENT_REGISTRATION_AT_AS_OF"
    assert result.evidence["state_temporal_scope"] == "CURRENT_STATE_AT_OBSERVATION"
    assert result.evidence["state_versions"] == {
        "Equipment:20400000-0000-4000-8000-000000000001": 1
    }
