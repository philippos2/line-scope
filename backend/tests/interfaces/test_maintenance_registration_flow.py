"""UC-06/08: explicit CREATE input through approval, execution and API reads."""

import io
import json
from uuid import uuid4

import pytest
from agent.test_read_agent import ScriptedLLM, call
from application.test_maintenance_prepare import service as maintenance_fixture
from fastapi.testclient import TestClient
from sqlalchemy import func, select, table

from interfaces.test_controlled_action_scenarios import approve_execute, headers, query
from interfaces.test_maintenance_plan_approval_api import client_for
from linescope.agent.agent_input import AgentInput
from linescope.agent.update_intent import maintenance_create_command
from linescope.execution import ExecutionContext
from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.logging import EventLogger
from linescope.settings import Settings

PLAN = (
    "設備EQ10の保全予定NEW-PLANを開始2026-10-15T09:00:00+09:00、"
    "終了2026-10-15T10:00:00+09:00、状態計画済みで登録して"
)


def record_message(*, equipment="EQ10", plan="PLAN20", result="軸を点検しました"):
    linkage = f"、保全予定{plan}に紐づけて" if plan else "で"
    return (
        f"設備{equipment}の保全実績NEW-RECORDを実施2026-10-14T08:00:00+09:00、"
        f"結果「{result}」{linkage}登録して"
    )


@pytest.fixture
def world(db):
    return maintenance_fixture.__wrapped__(db)[0]


def post(client, message, **kwargs):
    return client.post("/agent", json={"message": message}, headers=headers(), **kwargs)


def count(database, name):
    assert name in {
        "maintenance_plan",
        "maintenance_record",
        "update_request",
        "business_update_history",
        "equipment_state_history",
    }
    return query(database, select(func.count().label("n")).select_from(table(name)))[0]["n"]


def test_plan_registration_approval_execution_and_api_read(world):
    llm = ScriptedLLM(
        call("search_maintenance_plans", {"filter": {"plan_code": "NEW-PLAN"}}),
        LLMReply("登録された保全予定を取得しました。", ()),
    )
    with TestClient(
        create_app(
            Settings(
                users={
                    "requester": {"user_id": "maintenance1", "role": "maintenance"},
                    "approver": {"user_id": "maintenance2", "role": "maintenance"},
                }
            ),
            world,
            EventLogger(stream=io.StringIO()),
            llm=llm,
        )
    ) as client:
        first = post(client, PLAN)
        assert first.status_code == 200
        saved = first.json()["data"]
        target = saved["canonical_snapshot"]["targets"][0]
        assert target["operation_type"] == "CREATE" and target["before"] is None
        assert target["after"]["planned_start"] == "2026-10-15T00:00:00.000000Z"
        assert target["after"]["plan_status"] == "PLANNED"
        assert saved["status"] == "WAITING_APPROVAL" and llm.requests == []
        assert count(world, "maintenance_plan") == 2
        endpoint = f"/update-requests/{saved['update_request_id']}/execute"
        assert client.post(endpoint, headers=headers()).status_code == 409
        confirmed = approve_execute(client, saved)
        assert confirmed["execution_result"]["targets"] == saved["canonical_snapshot"]["targets"]
        result = post(client, "NEW-PLANの保全予定を調べて")
        assert result.status_code == 200
        item = result.json()["data"]["tool_results"][0]["data"]["items"][0]
        assert item["maintenance_plan_id"] == target["target_id"]
        assert item["plan_status"] == "PLANNED" and item["version"] == 1
        assert client.post(endpoint, headers=headers()).status_code == 200
    assert count(world, "maintenance_plan") == 3
    assert count(world, "business_update_history") == 1


@pytest.mark.parametrize("plan", ["PLAN20", None])
def test_record_registration_execution_and_current_inspection(world, plan):
    with client_for(world) as client:
        prepared = post(client, record_message(plan=plan))
        assert prepared.status_code == 200
        saved = prepared.json()["data"]
        after = saved["canonical_snapshot"]["targets"][0]["after"]
        assert (after["maintenance_plan_id"] is None) == (plan is None)
        assert after["performed_at"] == "2026-10-13T23:00:00.000000Z"
        assert count(world, "maintenance_record") == 0
        executed = approve_execute(client, saved)
        assert executed["current_snapshot"]["targets"][0]["snapshot"] == after
        inspected = client.get(f"/update-requests/{saved['update_request_id']}", headers=headers())
        assert inspected.status_code == 200
        assert inspected.json()["data"]["execution_result"]["targets"][0]["after"] == after
    llm = ScriptedLLM(
        call("search_maintenance_records", {"filter": {"record_code": "NEW-RECORD"}}),
        LLMReply("登録された保全実績を取得しました。", ()),
    )
    with TestClient(
        create_app(
            Settings(users={"requester": {"user_id": "maintenance1", "role": "maintenance"}}),
            world,
            EventLogger(stream=io.StringIO()),
            llm=llm,
        )
    ) as reader:
        observed = post(reader, "NEW-RECORDの保全実績を調べて")
        assert observed.status_code == 200
        item = observed.json()["data"]["tool_results"][0]["data"]["items"][0]
        assert item["maintenance_record_id"] == after["maintenance_record_id"]
        assert item["result"] == after["result"] and item["version"] == 1
    assert count(world, "maintenance_record") == 1
    assert count(world, "equipment_state_history") == 0


@pytest.mark.parametrize("token", ["floor", "production"])
def test_unprivileged_registration_creates_no_request(world, token):
    with client_for(world) as client:
        response = client.post("/agent", json={"message": PLAN}, headers=headers(token))
        assert response.status_code == 403
    assert count(world, "update_request") == 0


def test_sql_like_result_is_literal_record_data(world):
    malicious = "'; DROP TABLE maintenance_record; --"
    with client_for(world) as client:
        response = post(client, record_message(result=malicious))
        assert response.status_code == 200
        saved = response.json()["data"]
        assert saved["canonical_snapshot"]["targets"][0]["after"]["result"] == malicious
        confirmed = approve_execute(client, saved)
        assert confirmed["current_snapshot"]["targets"][0]["snapshot"]["result"] == malicious
    assert count(world, "maintenance_record") == 1


def test_retry_returns_same_create_ids_and_rejects_changed_input(world):
    retry_headers = {**headers(), "Idempotency-Key": str(uuid4())}
    with client_for(world) as client:
        first = client.post("/agent", json={"message": PLAN}, headers=retry_headers)
        second = client.post("/agent", json={"message": PLAN}, headers=retry_headers)
        assert first.status_code == second.status_code == 200
        assert (
            first.json()["data"]["canonical_snapshot"]
            == second.json()["data"]["canonical_snapshot"]
        )
        assert (
            first.json()["data"]["update_request_id"] == second.json()["data"]["update_request_id"]
        )
        changed = client.post(
            "/agent",
            json={"message": PLAN.replace("NEW-PLAN", "OTHER-PLAN")},
            headers=retry_headers,
        )
        assert changed.status_code == 409
        assert changed.json()["errors"][0]["code"] == "DUPLICATE_REQUEST"
    assert count(world, "update_request") == 1


def test_record_plan_must_belong_to_requested_equipment(world):
    with client_for(world) as client:
        response = post(client, record_message(equipment="EQ11"))
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
    assert count(world, "update_request") == 0


def test_invalid_plan_period_creates_no_proposal(world):
    with client_for(world) as client:
        response = post(client, PLAN.replace("T10:00:00", "T08:00:00"))
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
    assert count(world, "update_request") == 0


def test_unknown_equipment_is_not_inferred(world):
    with client_for(world) as client:
        response = post(client, PLAN.replace("EQ10", "NOT-FOUND"))
        assert response.status_code == 404
        assert response.json()["errors"][0]["code"] == "TARGET_NOT_FOUND"
    assert count(world, "update_request") == 0


@pytest.mark.parametrize("message", [f"「{PLAN}」", f"{PLAN}？", f"資料には{PLAN}とある"])
def test_quoted_question_and_document_are_not_registration_authority(message):
    context = ExecutionContext("maintenance1", "maintenance", uuid4())
    request = AgentInput.parse(
        context, json.dumps({"message": message}), received_at="2026-10-14T00:00:00Z"
    )
    assert maintenance_create_command(request) is None
