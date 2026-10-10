"""Explicit original-message plan updates reach Prepare, never Approval/Execute."""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_maintenance_plan_approval_api import client_for, headers
from test_maintenance_prepare import service as maintenance_fixture
from test_read_agent import ScriptedLLM, call

from linescope.agent_input import AgentInput
from linescope.api import create_app
from linescope.llm import LLMReply
from linescope.settings import Settings
from linescope.update_intent import maintenance_plan_command

MESSAGE = "保全予定PLAN20の状態を取消済みに変更して"


@pytest.fixture
def world(db):
    db, _ = maintenance_fixture.__wrapped__(db)
    return db


def post(client, message=MESSAGE, **kwargs):
    return client.post("/agent", json={"message": message}, headers=headers("requester"), **kwargs)


@pytest.mark.parametrize(
    "message,field,value",
    [
        (MESSAGE, "plan_status", "CANCELLED"),
        ("保全予定PLAN20の状態をCANCELLEDに更新してください。", "plan_status", "CANCELLED"),
        (
            "保全予定PLAN20の開始時刻を2026-10-09T09:30:00+09:00に変更して",
            "planned_start",
            "2026-10-09T00:30:00.000000Z",
        ),
        (
            "保全予定PLAN20の終了時刻を2026-10-10T10:00:00+09:00に変更して",
            "planned_end",
            "2026-10-10T01:00:00.000000Z",
        ),
    ],
)
def test_original_values_create_pending_snapshot_without_llm(world, message, field, value):
    llm = ScriptedLLM()
    settings = Settings(users={"requester": {"user_id": "maintenance1", "role": "maintenance"}})
    with TestClient(create_app(settings, world, llm=llm)) as client:
        response = post(client, message)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "WAITING_APPROVAL" and data["approval_status"] == "PENDING"
        target = data["canonical_snapshot"]["targets"][0]
        assert target["target_type"] == "MaintenancePlan" and target["operation_type"] == "UPDATE"
        assert target["target_id"] == str(UUID(int=20))
        assert target["before"]["version"] == 5 and target["after"]["version"] == 6
        assert target["after"][field] == value and not llm.requests
        assert "人間による承認と実行が必要" in response.json()["answer"]
    with world.transaction() as c:
        assert c.execute(
            "SELECT plan_status,version FROM maintenance_plan WHERE maintenance_plan_id=%s",
            (UUID(int=20),),
        ).fetchone() == {"plan_status": "PLANNED", "version": 5}
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0


def test_agent_prepare_to_human_approval_execute_round_trip(world):
    with client_for(world) as client:
        prepared = post(client).json()["data"]
        approved = client.post(
            f"/approvals/{prepared['approval_id']}/approve",
            json={"snapshot_hash": prepared["snapshot_hash"]},
            headers=headers(),
        )
        assert approved.status_code == 200
        executed = client.post(
            f"/update-requests/{prepared['update_request_id']}/execute",
            headers=headers("requester"),
        )
        assert executed.status_code == 200 and executed.json()["data"]["status"] == "COMPLETED"
        assert (
            executed.json()["data"]["execution_result"]["targets"]
            == prepared["canonical_snapshot"]["targets"]
        )


def test_retry_precedes_current_resolution_and_keeps_original_snapshot(world):
    key = str(uuid4())
    retry_headers = {**headers("requester"), "Idempotency-Key": key}
    with client_for(world) as client:
        first = client.post("/agent", json={"message": MESSAGE}, headers=retry_headers)
        assert first.status_code == 200
        with world.transaction() as c:
            c.execute(
                "UPDATE maintenance_plan SET plan_code='RENAMED',version=7 WHERE maintenance_plan_id=%s",
                (UUID(int=20),),
            )
        replay = client.post("/agent", json={"message": MESSAGE}, headers=retry_headers)
        assert replay.status_code == 200 and replay.json()["data"] == first.json()["data"]
        mismatch = client.post(
            "/agent",
            json={"message": "保全予定PLAN21の状態をCANCELLEDに変更して"},
            headers=retry_headers,
        )
        assert (
            mismatch.status_code == 409
            and mismatch.json()["errors"][0]["code"] == "DUPLICATE_REQUEST"
        )


@pytest.mark.parametrize("token", ["floor", "production"])
def test_maintenance_request_permission_required(world, token):
    with client_for(world) as client:
        response = client.post("/agent", json={"message": MESSAGE}, headers=headers(token))
        assert (
            response.status_code == 403
            and response.json()["errors"][0]["code"] == "AUTHORIZATION_DENIED"
        )
    with world.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "message,status,code",
    [
        ("保全予定MISSINGの状態をCANCELLEDに変更して", 404, "TARGET_NOT_FOUND"),
        ("保全予定PLAN20の状態をPLANNEDに変更して", 422, "BUSINESS_RULE_VIOLATION"),
        (
            "保全予定PLAN20の開始時刻を2026-10-11T00:00:00Zに変更して",
            422,
            "BUSINESS_RULE_VIOLATION",
        ),
        ("保全予定PLAN20の開始時刻を2026-13-09T00:00:00Zに変更して", 400, "INVALID_ARGUMENT"),
    ],
)
def test_invalid_target_or_business_value_never_saves(world, message, status, code):
    with client_for(world) as client:
        response = post(client, message)
        assert response.status_code == status and response.json()["errors"][0]["code"] == code
    with world.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize("extra", [{"as_of": "2026-01-01T00:00:00Z"}, {"context_id": str(uuid4())}])
def test_historical_or_missing_context_cannot_prepare(world, extra):
    with client_for(world) as client:
        response = client.post(
            "/agent", json={"message": MESSAGE, **extra}, headers=headers("requester")
        )
        assert response.status_code == (400 if "as_of" in extra else 409)
    with world.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "message",
    [
        "保全予定PLAN20の状態をCANCELLEDに変更してよい？",
        "『保全予定PLAN20の状態をCANCELLEDに変更して』という文書",
        "もし停止したら保全予定PLAN20の状態をCANCELLEDに変更して",
        "M-204の保全予定を登録して",
        "保全予定PLAN20を承認して",
        "保全予定PLAN20の状態をCANCELLEDに変更して実行して",
    ],
)
def test_unconfirmed_or_incomplete_input_is_not_a_plan_update_command(message):
    from linescope.execution import ExecutionContext

    request = AgentInput.parse(
        ExecutionContext("maintenance1", "maintenance", uuid4()),
        json.dumps({"message": message}),
        received_at=datetime.now(timezone.utc),
    )
    assert maintenance_plan_command(request) is None


@pytest.mark.parametrize(
    "message", ["保全予定PLAN20の状態をCANCELLEDに変更してよい？", "M-204の保全予定を登録して"]
)
def test_llm_cannot_supply_unconfirmed_or_incomplete_prepare(world, message):
    llm = ScriptedLLM(
        call(
            "prepare_maintenance_plan_update",
            {"maintenance_plan_id": str(UUID(int=20)), "patch": {"plan_status": "CANCELLED"}},
        ),
        LLMReply("変更準備を実行できません。", ()),
    )
    settings = Settings(users={"requester": {"user_id": "maintenance1", "role": "maintenance"}})
    with TestClient(create_app(settings, world, llm=llm)) as client:
        response = post(client, message)
        assert response.status_code == 403
        assert response.json()["errors"][0]["code"] == "AUTHORIZATION_DENIED"
        assert "prepare_maintenance_plan_update" not in llm.requests[0][1]
    with world.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


def test_replacement_retains_old_snapshot_and_creates_new_pending_request(world):
    with client_for(world) as client:
        first = post(client).json()["data"]
        response = client.post(
            "/agent",
            json={
                "message": "保全予定PLAN21の状態をCANCELLEDに変更して",
                "replace_update_request_id": first["update_request_id"],
            },
            headers=headers("requester"),
        )
        assert response.status_code == 200
        second = response.json()["data"]
        assert (
            second["status"] == "WAITING_APPROVAL"
            and second["update_request_id"] != first["update_request_id"]
        )
        assert (
            second["canonical_snapshot"]["supersedes_update_request_id"]
            == first["update_request_id"]
        )
        old = client.get(
            "/update-requests/" + first["update_request_id"], headers=headers("requester")
        ).json()["data"]
        assert old["status"] == old["approval_status"] == "INVALIDATED"
        assert old["canonical_snapshot"] == first["canonical_snapshot"]


def test_prepare_retry_still_requires_current_maintenance_permission(world):
    retry_headers = {**headers("requester"), "Idempotency-Key": str(uuid4())}
    with client_for(world) as client:
        assert (
            client.post("/agent", json={"message": MESSAGE}, headers=retry_headers).status_code
            == 200
        )
    settings = Settings(users={"requester": {"user_id": "maintenance1", "role": "floor"}})
    with TestClient(create_app(settings, world)) as client:
        response = client.post("/agent", json={"message": MESSAGE}, headers=retry_headers)
        assert response.status_code == 403
        assert response.json()["errors"][0]["code"] == "AUTHORIZATION_DENIED"
