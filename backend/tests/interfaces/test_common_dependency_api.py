import pytest
from agent.test_read_agent import ScriptedLLM, call
from application.test_common_dependencies import arguments
from fastapi.testclient import TestClient
from graph.test_common_dependency_reader import reader_world as reader_world
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_rebuild_controller import adapters as adapters

from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.settings import Settings


@pytest.mark.parametrize("partial", [False, True])
def test_common_tool_agent_and_http_preserve_paths_and_partial_status(
    db, reader_world, adapters, partial
):
    args = arguments(**({"requested_max_paths": 1} if partial else {}))
    llm = ScriptedLLM(
        call("find_common_dependencies", args),
        LLMReply("共通依存候補と対象別経路を確認しました。", ()),
    )
    settings = Settings(
        users={"token": {"user_id": "manager1", "role": "manager"}}, graph_max_paths=20
    )
    with TestClient(create_app(settings, db, llm=llm, graph_driver=adapters[1].driver)) as client:
        response = client.post(
            "/agent",
            json={"message": "P-100とP-200の共通依存を調べて"},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ("partial" if partial else "ok")
    result = body["data"]["tool_results"][0]
    assert result["tool"] == "find_common_dependencies"
    assert result["data"]["complete"] is (not partial)
    assert len(result["data"]["common_candidates"]) == (0 if partial else 6)
    assert len(result["data"]["representative_paths"]) == (0 if partial else 12)
    evidence = body["evidence"]["tool_results"][0]
    assert evidence["representative_paths"] == result["data"]["representative_paths"]
    assert evidence["graph_generation"] == reader_world[1]
    assert "find_common_dependencies" in llm.requests[0][1]
    assert not any(name.startswith("prepare_") for name in llm.requests[0][1])
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


def test_noncurrent_graph_common_tool_does_not_return_candidate_paths(db, reader_world, adapters):
    with db.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET fatal_error='TEST_UNAVAILABLE'")
    llm = ScriptedLLM(
        call("find_common_dependencies", arguments()), LLMReply("使用できません。", ())
    )
    settings = Settings(users={"token": {"user_id": "manager1", "role": "manager"}})
    with TestClient(create_app(settings, db, llm=llm, graph_driver=adapters[1].driver)) as client:
        response = client.post(
            "/agent",
            json={"message": "共通依存を調べて"},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 503
    body = response.json()
    assert body["errors"][0]["code"] == "GRAPH_UNAVAILABLE"
    assert body["data"]["tool_results"] == []
    assert body["evidence"]["tool_results"] == []
