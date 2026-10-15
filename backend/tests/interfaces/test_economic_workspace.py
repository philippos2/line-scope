from uuid import uuid4

import pytest
from agent.test_read_agent import ScriptedLLM, call
from fastapi.testclient import TestClient

from interfaces.test_economic_inputs_api import (
    approve,
    body,
    client_for,
    execute,
    headers,
    identifier,
    prepare,
)
from interfaces.test_economic_inputs_api import settings as api_settings
from interfaces.test_economic_inputs_api import world as seeded_world
from linescope.application.tools import ToolDispatcher
from linescope.execution import ExecutionContext
from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app


@pytest.fixture
def world(db):
    return seeded_world.__wrapped__(db)


def registered(client, code="ECONOMIC"):
    saved = prepare(client, body(code))
    assert approve(client, saved).status_code == 200
    assert execute(client, saved).status_code == 200
    return identifier(saved)


@pytest.mark.parametrize("role,status", [("maintenance", 200), ("production", 200), ("floor", 403)])
def test_search_uses_economic_visibility_even_for_empty_database(world, role, status):
    with client_for(world) as client:
        result = client.post("/economic-inputs/search", json={}, headers=headers(role))
        assert result.status_code == status
        if status == 200:
            assert result.json()["data"]["items"] == []


def test_search_equipment_and_code_filters_do_not_interpret_sql_or_like_wildcards(world):
    with client_for(world) as client:
        record = registered(client, "COST-' OR true --")
        other = body("OTHER")
        other["input"]["equipment_id"] = "20800000-0000-4000-8000-000000000001"
        contrasting = prepare(client, other)
        assert (
            approve(client, contrasting).status_code
            == execute(client, contrasting).status_code
            == 200
        )
        for filters in ({"equipment_query": "M-204"}, {"input_code": "COST-' OR true --"}):
            result = client.post(
                "/economic-inputs/search", json={"filter": filters}, headers=headers()
            ).json()["data"]
            assert [row["economic_input_id"] for row in result["items"]] == [record]
            assert result["items"][0]["equipment_name"] == "Demo machine M-204"
            assert "payload" not in result["items"][0]
        result = client.post(
            "/economic-inputs/search", json={"filter": {"equipment_query": "%"}}, headers=headers()
        ).json()["data"]
        assert result["items"] == []


def test_cursor_pages_all_candidates_and_is_bound_to_role_user_and_filter(world):
    with client_for(world) as client:
        expected = {registered(client, code) for code in ("A", "B", "C")}
        first = client.post(
            "/economic-inputs/search", json={"page_size": 1}, headers=headers()
        ).json()["data"]
        second = client.post(
            "/economic-inputs/search",
            json={"page_size": 2, "cursor": first["next_cursor"]},
            headers=headers(),
        ).json()["data"]
        assert {row["economic_input_id"] for row in first["items"] + second["items"]} == expected
        assert second["next_cursor"] is None
        assert (
            client.post(
                "/economic-inputs/search",
                json={"cursor": first["next_cursor"]},
                headers=headers("approver"),
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/economic-inputs/search",
                json={"filter": {"input_code": "A"}, "cursor": first["next_cursor"]},
                headers=headers(),
            ).status_code
            == 400
        )


def test_search_rejects_authority_fields_without_reading_data(world):
    with client_for(world) as client:
        result = client.post("/economic-inputs/search", json={"role": "manager"}, headers=headers())
        assert result.status_code == 400


def test_tools_keep_server_calculation_source_and_version_evidence(world):
    with client_for(world) as client:
        record = registered(client)
    dispatcher = ToolDispatcher(world)
    context = ExecutionContext("reader", "production", uuid4())
    candidates = dispatcher.run(
        context, "search_economic_inputs", {"filter": {"equipment_query": "M-204"}}
    )
    assert candidates.data["items"][0]["economic_input_id"] == record
    result = dispatcher.run(context, "get_economic_input", {"economic_input_id": record})
    assert result.evidence["version"] == 1 and result.evidence["economic_input_id"] == record
    assert result.data["source"] == "REGISTERED_INPUT"
    assert result.data["calculation"]["recommendation"] is None


def test_agent_uses_registered_tools_and_deterministic_unknown_summary_without_prepare(world):
    with client_for(world) as client:
        record = registered(client)
    llm = ScriptedLLM(
        call("search_economic_inputs", {"filter": {"input_code": "ECONOMIC"}}),
        call("get_economic_input", {"economic_input_id": record}),
        LLMReply("すべて安全で交換が最適です", ()),
    )
    with TestClient(create_app(api_settings(), world, llm=llm)) as client:
        result = client.post(
            "/agent",
            json={"message": "登録済み経済入力ECONOMICの見積と不明事項を確認して"},
            headers=headers(),
        )
    data = result.json()
    assert result.status_code == 200
    assert "1900000円" in data["answer"] and "交換総額不明" in data["answer"]
    assert "安全で交換が最適" not in data["answer"]
    assert [row["tool"] for row in data["data"]["tool_results"]] == [
        "search_economic_inputs",
        "get_economic_input",
    ]
    assert not any(
        "prepare" in name or "execute" in name or "approve" in name for name in llm.requests[0][1]
    )


def test_agent_denied_economic_read_cannot_publish_unverified_costs(world):
    llm = ScriptedLLM(call("search_economic_inputs", {"filter": {}}), LLMReply("費用は0円です", ()))
    with TestClient(create_app(api_settings(), world, llm=llm)) as client:
        result = client.post(
            "/agent", json={"message": "経済入力を検索して"}, headers=headers("floor")
        ).json()
    assert result["answer"] is None
    assert result["errors"][0]["code"] == "AUTHORIZATION_DENIED"
    assert result["data"]["tool_results"] == []


def test_formal_m204_request_does_not_enter_fixture_comparison(world):
    from linescope.application.demo_decision import DemoDecisionFlow

    assert not DemoDecisionFlow.matches("M-204の経済入力と修理費用を比較して")
    assert DemoDecisionFlow.matches("M-204の修理・交換を比較して")
