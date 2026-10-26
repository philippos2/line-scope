"""HTTP Graph analysis uses real storage and server-owned configuration."""

import os

import pytest
from agent.test_read_agent import ScriptedLLM, call
from application.test_graph_analysis import world as world
from fastapi.testclient import TestClient
from graph.test_analysis_reader import built as built
from graph.test_analysis_traversal import chain as chain
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_rebuild_control import store as store

from interfaces.demo_read_support import graph_message, readonly_schemas
from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.settings import Settings


def test_api_past_time_is_server_bound_and_not_a_historical_state_restore(world):
    db, driver, origin, _, _, _, _, _ = world
    llm = ScriptedLLM(
        call("get_equipment_state", {"equipment_id": origin}),
        call(
            "trace_downstream_impact",
            {"target": {"entity_type": "Equipment", "entity_id": origin}},
        ),
        LLMReply("指定時刻の依存関係を確認しました。", ()),
    )
    settings = Settings(users={"token": {"user_id": "manager1", "role": "manager"}})
    with TestClient(create_app(settings, db, llm=llm, graph_driver=driver)) as client:
        state_response = client.post(
            "/agent",
            json={
                "message": "M-204の登録状態は？",
            },
            headers={"Authorization": "Bearer token"},
        )
        response = client.post(
            "/agent",
            json={
                "message": graph_message(
                    "trace_downstream_impact",
                    {"target": {"entity_type": "Equipment", "entity_id": origin}},
                ),
                "as_of": "2026-10-08T09:00:00+09:00",
            },
            headers={"Authorization": "Bearer token"},
        )
    assert state_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    evidence = [
        next(
            row
            for row in state_response.json()["evidence"]["tool_results"]
            if row["tool"] == "get_equipment_state"
        ),
        next(
            row
            for row in body["evidence"]["tool_results"]
            if row["tool"] == "trace_downstream_impact"
        ),
    ]
    assert evidence[1]["as_of"] == "2026-10-08T00:00:00.000000Z"
    assert evidence[1]["analysis_mode"] == "EXPLICIT_HISTORICAL"
    assert (
        len(
            next(
                row["data"]["reached_nodes"]
                for row in body["data"]["tool_results"]
                if row["tool"] == "trace_downstream_impact"
            )
        )
        == 2
    )
    assert (
        "requested_as_of" not in evidence[0]
    )  # Registered-state questions read the current registration.
    assert evidence[1]["request_temporal_scope"] == "CURRENT_REGISTRATION_AT_AS_OF"
    assert "完全復元ではありません" in body["answer"]
    assert not llm.requests  # The code binds the time; model-written Tool arguments are not used.


@pytest.mark.parametrize("tool", ["trace_downstream_impact", "trace_upstream_dependencies"])
@pytest.mark.parametrize("owned", [False, True])
def test_http_agent_returns_paths_and_authoritative_state_evidence(world, tool, owned):
    db, driver, origin, _, product, _, _, _ = world
    downstream = tool == "trace_downstream_impact"
    args = {
        "target": {
            "entity_type": "Equipment" if downstream else "Product",
            "entity_id": origin if downstream else product,
        }
    }
    llm = ScriptedLLM(call(tool, args), LLMReply("経路を確認しました。", ()))
    config = (
        {
            "neo4j_uri": os.environ["LINESCOPE_TEST_NEO4J_URI"],
            "neo4j_user": "neo4j",
            "neo4j_password": "disposable-graph-password",
        }
        if owned
        else {}
    )
    settings = Settings(users={"token": {"user_id": "manager1", "role": "manager"}}, **config)
    with TestClient(
        create_app(settings, db, llm=llm, graph_driver=None if owned else driver)
    ) as client:
        response = client.post(
            "/agent",
            json={"message": graph_message(tool, args)},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    if downstream:
        assert "2件の依存到達候補" in body["answer"]
        assert "未評価" in body["answer"]
        assert origin not in body["answer"]
    else:
        assert "上流に2件の依存到達要素" in body["answer"]
        assert "1段上流1件、2段以上の上流1件" in body["answer"]
        assert "未評価" in body["answer"]
        assert "下流" not in body["answer"]
        assert product not in body["answer"]
    result = body["data"]["tool_results"][0]["data"]
    evidence = body["evidence"]["tool_results"][0]
    assert result["complete"] and len(result["reached_nodes"]) == 2
    assert evidence["state_versions"] == {"Equipment:" + origin: 3}
    assert evidence["representative_paths"] == result["representative_paths"]
    assert result["effective_limits"] == {
        "max_depth": 16,
        "max_nodes": 1000,
        "max_paths": 1000,
        "timeout_ms": 5000,
    }
    assert "execute" not in readonly_schemas(db)
    # The injected driver is borrowed, so it remains usable after API shutdown.
    driver.verify_connectivity()


def test_http_graph_authorization_uses_authenticated_role(world):
    db, driver, origin, _, _, _, _, _ = world
    llm = ScriptedLLM(
        call(
            "trace_downstream_impact", {"target": {"entity_type": "Equipment", "entity_id": origin}}
        ),
        LLMReply("影響なし", ()),
    )
    settings = Settings(users={"token": {"user_id": "floor1", "role": "floor"}})
    with TestClient(create_app(settings, db, llm=llm, graph_driver=driver)) as client:
        response = client.post(
            "/agent",
            json={
                "message": graph_message(
                    "trace_downstream_impact",
                    {"target": {"entity_type": "Equipment", "entity_id": origin}},
                )
            },
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "AUTHORIZATION_DENIED"
    assert response.json()["evidence"] == {}


@pytest.mark.parametrize("rebuilding", [False, True])
def test_http_partial_and_rebuilding_follow_graph_error_contract(world, rebuilding):
    db, driver, origin, _, _, _, _, _ = world
    if rebuilding:
        with db.transaction() as connection:
            connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
    args = {"target": {"entity_type": "Equipment", "entity_id": origin}, "requested_max_paths": 1}
    llm = ScriptedLLM(call("trace_downstream_impact", args), LLMReply("確認結果です。", ()))
    settings = Settings(users={"token": {"user_id": "manager1", "role": "manager"}})
    with TestClient(create_app(settings, db, llm=llm, graph_driver=driver)) as client:
        response = client.post(
            "/agent",
            json={"message": graph_message("trace_downstream_impact", args)},
            headers={"Authorization": "Bearer token"},
        )
    body = response.json()
    if rebuilding:
        assert response.status_code == 503 and body["status"] == "error"
        assert body["errors"][0]["code"] == "GRAPH_REBUILDING"
        assert body["evidence"] == {}
    else:
        assert response.status_code == 200 and body["status"] == "partial"
        assert "探索は不完全" in body["answer"]
        assert body["data"]["tool_results"][0]["data"]["limit_reason"] == "PATH_COUNT"
        assert body["data"]["tool_results"][0]["data"]["analysis_mode"] == "CURRENT"
