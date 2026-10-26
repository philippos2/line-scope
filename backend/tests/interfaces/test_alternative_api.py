from datetime import datetime, timezone
from uuid import uuid4

import pytest
from agent.test_read_agent import ScriptedLLM, call
from fastapi.testclient import TestClient
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from sqlalchemy import column, select, table, update
from sqlalchemy.dialects.postgresql.psycopg import dialect

from interfaces.demo_read_support import graph_message, readonly_schemas
from linescope.application.graph_analysis import GraphAnalysis
from linescope.application.graph_request import GraphLimits
from linescope.application.reads import ToolError
from linescope.demo_graph_seed import demo_id
from linescope.execution import ExecutionContext
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_states import GraphStateReader
from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.settings import Settings

P = {"entity_type": "Product", "entity_id": str(demo_id("P-100"))}
M = {"entity_type": "Equipment", "entity_id": "20400000-0000-4000-8000-000000000001"}
AS_OF = datetime(2026, 10, 13, tzinfo=timezone.utc)


def arguments(**extra):
    return {"important_targets": [P], "excluded_nodes": [M], **extra}


def service(db, reader_world):
    return GraphAnalysis(
        reader_world[0],
        GraphStateReader(db),
        system_limits=GraphLimits(16, 20, 100, 5000),
        budget_factory=GraphAnalysisBudget,
        clock=lambda: AS_OF,
    )


@pytest.mark.parametrize("role", ["maintenance", "production", "manager"])
def test_authorized_tool_runs_complete_alternative_analysis(db, reader_world, role):
    result = service(db, reader_world).call(
        ExecutionContext("actor", role, uuid4()), "find_alternative_paths", arguments()
    )
    assert result.data["complete"] and result.data["determination"] == "DETERMINATE"
    assert result.data["target_results"][0]["after"]["determination"] == "ESTABLISHED"
    assert result.data["alternatives"][0]["availability"] == "AVAILABLE"
    assert result.evidence["tool"] == "find_alternative_paths"
    assert result.data["effective_limits"]["timeout_ms"] == 5000


@pytest.mark.parametrize("partial", [False, True])
def test_native_named_tool_http_and_server_evidence_are_connected(
    db, reader_world, adapters, partial
):
    args = arguments(**({"requested_max_paths": 1} if partial else {}))
    llm = ScriptedLLM(
        call("find_alternative_paths", args),
        LLMReply("構造上の代替候補を確認しました。能力・安全性は未評価です。", ()),
    )
    settings = Settings(
        users={"token": {"user_id": "manager1", "role": "manager"}}, graph_max_paths=100
    )
    with TestClient(create_app(settings, db, llm=llm, graph_driver=adapters[1].driver)) as client:
        response = client.post(
            "/agent",
            json={"message": graph_message("find_alternative_paths", args)},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ("partial" if partial else "ok")
    result = body["data"]["tool_results"][0]
    assert result["tool"] == "find_alternative_paths"
    assert result["data"]["complete"] is (not partial)
    assert result["data"]["determination"] == ("INDETERMINATE" if partial else "DETERMINATE")
    evidence = body["evidence"]["tool_results"][0]
    assert evidence["representative_paths"] == result["data"]["representative_paths"]
    assert evidence["graph_generation"] == reader_world[1]
    assert "find_alternative_paths" in readonly_schemas(db)
    schema = readonly_schemas(db)["find_alternative_paths"]
    assert set(schema["required"]) == {"important_targets", "excluded_nodes"}
    assert schema["additionalProperties"] is False
    assert "relation_types" not in schema["properties"]
    assert "timeout_ms" not in schema["properties"]
    assert not any(name.startswith("prepare_") for name in readonly_schemas(db))
    relation = table("update_request", column("update_request_id"))
    statement = select(relation).compile(dialect=dialect())
    with db.transaction() as connection:
        assert connection.execute(str(statement), statement.params).fetchall() == []


def test_noncurrent_graph_returns_no_alternative_or_evidence(db, reader_world, adapters):
    control = table("graph_projection_control", column("fatal_error"))
    statement = update(control).values(fatal_error="TEST_UNAVAILABLE").compile(dialect=dialect())
    with db.transaction() as connection:
        connection.execute(str(statement), statement.params)
    llm = ScriptedLLM(call("find_alternative_paths", arguments()), LLMReply("利用できません。", ()))
    settings = Settings(users={"token": {"user_id": "manager1", "role": "manager"}})
    with TestClient(create_app(settings, db, llm=llm, graph_driver=adapters[1].driver)) as client:
        response = client.post(
            "/agent",
            json={"message": graph_message("find_alternative_paths", arguments())},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "GRAPH_UNAVAILABLE"
    assert response.json()["data"] == {}
    assert response.json()["evidence"] == {}


@pytest.mark.parametrize(
    "role,args,code",
    [
        ("floor", arguments(), "AUTHORIZATION_DENIED"),
        ("manager", arguments(relation_types=["SUPPLIES"]), "INVALID_ARGUMENT"),
        ("manager", arguments(timeout_ms=1), "INVALID_ARGUMENT"),
        ("manager", arguments(explicit_as_of="now"), "INVALID_ARGUMENT"),
    ],
)
def test_authority_and_arguments_fail_before_opening_graph(db, role, args, code):
    class NoReader:
        def open(self, *args):
            pytest.fail("Invalid request must not open Graph storage")

    tool = GraphAnalysis(
        NoReader(),
        None,
        system_limits=GraphLimits(16, 20, 100, 5000),
        budget_factory=GraphAnalysisBudget,
        clock=lambda: AS_OF,
    )
    with pytest.raises(ToolError) as caught:
        tool.call(ExecutionContext("actor", role, uuid4()), "find_alternative_paths", args)
    assert caught.value.code == code


def test_missing_exclusion_rejects_entire_tool(db, reader_world):
    with pytest.raises(ToolError) as caught:
        service(db, reader_world).call(
            ExecutionContext("actor", "manager", uuid4()),
            "find_alternative_paths",
            arguments(excluded_nodes=[M, {"entity_type": "Equipment", "entity_id": str(uuid4())}]),
        )
    assert caught.value.code == "TARGET_NOT_FOUND"


def supply_world(db, adapters, state):
    """Independent initial fixture, never a product state-change command."""
    from linescope.demo_file_seed import seed_demo_file
    from linescope.graph.administration import GraphAdministration

    db.migrate()
    seed_demo_file(db, "docs/demo/data/scenario1.json")
    with db.transaction() as connection:
        connection.execute("UPDATE infrastructure_supply_state SET supply_state=%s", (state,))
    GraphAdministration(db, adapters[1].driver).rebuild()
    return {
        "important_targets": [{"entity_type": "Product", "entity_id": str(demo_id("P-100"))}],
        "excluded_nodes": [{"entity_type": "Equipment", "entity_id": str(demo_id("M-204"))}],
    }


@pytest.mark.parametrize("state", ["UNAVAILABLE", "UNKNOWN"])
def test_registered_common_power_prevents_available_substitute(db, adapters, state):
    args = supply_world(db, adapters, state)
    settings = Settings(users={"token": {"user_id": "reader", "role": "manager"}})
    with TestClient(create_app(settings, db, graph_driver=adapters[1].driver)) as api:
        response = api.post(
            "/agent",
            headers={"Authorization": "Bearer token"},
            json={
                "message": graph_message("find_alternative_paths", args),
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    candidate = body["data"]["tool_results"][0]["data"]["alternatives"][0]["candidates"][0]
    assert candidate["candidate"]["entity_id"] == str(demo_id("M-208"))
    assert candidate["structure"]["determination"] == "ESTABLISHED"
    assert candidate["availability"] == state
    evidence = body["evidence"]["tool_results"][0]
    fact = evidence["current_resource_states"][0]
    assert fact["supply_state"] == state and fact["version"] == 1
    assert fact["record_reference"] == {
        "infrastructure_resource_id": str(demo_id("R-02")),
        "version": 1,
    }
    assert evidence["state_versions"]["InfrastructureResource:" + str(demo_id("R-02"))] == 1
    assert fact["registered_at"] and evidence["state_observed_at"]
