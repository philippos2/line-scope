import json
import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_proposals import NOW, PREPARE_HASH, category_snapshot, context, snapshot
from test_read_agent import ScriptedLLM, call

from linescope.agent_input import AgentInput, ConversationStore
from linescope.api import create_app
from linescope.llm import LLMReply, OllamaClient
from linescope.proposals import ProposalStore
from linescope.reads import ToolError
from linescope.settings import Settings

HEADERS = {"Authorization": "Bearer token"}


def settings():
    return Settings(
        users={
            "token": {"user_id": "floor1", "role": "floor"},
            "other": {"user_id": "other", "role": "floor"},
        }
    )


@pytest.fixture
def seeded(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'M-204','Machine','machine',true)",
            (UUID(int=1),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'STOPPED')",
            (UUID(int=1),),
        )
    return db


def test_agent_api_uses_real_reads_and_server_evidence(seeded):
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"equipment_code": "M-204"}}),
        call("get_equipment_state"),
        LLMReply("M-204はSTOPPEDです", ()),
    )
    with TestClient(create_app(settings(), seeded, llm=llm)) as client:
        result = client.post("/agent", json={"message": "M-204の状態を教えて"}, headers=HEADERS)
    assert result.status_code == 200
    body = result.json()
    assert body["answer"] == "M-204はSTOPPEDです" and body["status"] == "ok"
    assert body["data"]["tool_results"][1]["data"]["state_code"] == "STOPPED"
    assert body["evidence"]["tool_results"][1]["source"] == "POSTGRESQL"
    assert len(body["data"]["tool_trace"]) == 2 and not body["errors"]
    with seeded.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "body",
    [
        "{}",
        '{"message":"x","role":"manager"}',
        '{"message":"x","message":"y"}',
        '{"message":"x","as_of":"2099-01-01T00:00:00Z"}',
        '{"message":"x","context_id":null}',
    ],
)
def test_invalid_body_rejected_before_llm(body):
    llm = ScriptedLLM()
    with TestClient(create_app(settings(), llm=llm)) as client:
        result = client.post(
            "/agent", content=body, headers={**HEADERS, "Content-Type": "application/json"}
        )
    assert result.status_code == 400 and not llm.requests


def test_authentication_precedes_body_and_dependencies():
    with TestClient(create_app(settings())) as client:
        result = client.post("/agent", content="not JSON")
    assert result.status_code == 401


def test_no_model_does_not_disable_health():
    with TestClient(create_app(settings())) as client:
        assert client.get("/health", headers=HEADERS).status_code == 200
        result = client.post("/agent", json={"message": "query"}, headers=HEADERS)
    assert (
        result.status_code == 503 and result.json()["errors"][0]["code"] == "DEPENDENCY_UNAVAILABLE"
    )


def test_clarification_context_is_owned_and_continues_with_original_message():
    llm = ScriptedLLM(LLMReply("対象不明", ()), LLMReply("対象不明", ()))
    with TestClient(create_app(settings(), llm=llm)) as client:
        first = client.post("/agent", json={"message": "あの設備の状態は？"}, headers=HEADERS)
        identity = first.json()["context_id"]
        assert first.status_code == 200 and first.json()["data"]["needs_input"]
        assert identity
        denied = client.post(
            "/agent",
            json={"message": "M-204", "context_id": identity},
            headers={"Authorization": "Bearer other"},
        )
        assert denied.status_code == 403
        second = client.post(
            "/agent", json={"message": "M-204", "context_id": identity}, headers=HEADERS
        )
    assert second.status_code == 200 and second.json()["context_id"] == identity
    assert [m["content"] for m in llm.requests[1][0] if m["role"] == "user"] == [
        "あの設備の状態は？",
        "M-204",
    ]


def test_context_expiry_is_409_before_llm():
    now = [0]
    store = ConversationStore(clock=lambda: now[0])
    identity = store.create(context(), {"messages": ["query"]})
    now[0] = 1800
    llm = ScriptedLLM()
    with TestClient(create_app(settings(), llm=llm, conversations=store)) as client:
        result = client.post(
            "/agent", json={"message": "query", "context_id": identity}, headers=HEADERS
        )
    assert result.status_code == 409 and result.json()["errors"][0]["code"] == "CONTEXT_EXPIRED"
    assert not llm.requests


def test_saved_prepare_replay_precedes_expired_context_and_llm(seeded):
    identity = str(uuid4())
    key = str(uuid4())
    body = {"message": "設備M-204の状態をSTOPPEDに変更して", "context_id": identity}
    incoming = AgentInput.parse(context(), json.dumps(body), received_at=NOW, idempotency_key=key)
    saved = ProposalStore(seeded).save(
        context(),
        snapshot(),
        key,
        prepare_input_hash=PREPARE_HASH,
        agent_input_hash=incoming.input_hash,
    )
    with TestClient(create_app(settings(), seeded)) as client:
        result = client.post("/agent", json=body, headers={**HEADERS, "Idempotency-Key": key})
        mismatch = client.post(
            "/agent",
            json={**body, "message": "different"},
            headers={**HEADERS, "Idempotency-Key": key},
        )
    assert result.status_code == 200 and result.json()["data"]["update_request_id"] == str(
        saved.update_request_id
    )
    assert result.json()["data"]["canonical_snapshot"] == saved.snapshot.data
    assert (
        mismatch.status_code == 409 and mismatch.json()["errors"][0]["code"] == "DUPLICATE_REQUEST"
    )


def test_replay_revalidates_request_role(seeded):
    key = str(uuid4())
    body = {"message": "M-204の保全予定を登録して"}
    incoming = AgentInput.parse(context(), json.dumps(body), received_at=NOW, idempotency_key=key)
    owner = context("floor1", "manager")
    ProposalStore(seeded).save(
        owner,
        category_snapshot("maintenance", owner),
        key,
        prepare_input_hash=PREPARE_HASH,
        agent_input_hash=incoming.input_hash,
    )
    with TestClient(create_app(settings(), seeded)) as client:
        result = client.post("/agent", json=body, headers={**HEADERS, "Idempotency-Key": key})
    assert result.status_code == 403


@pytest.mark.parametrize(
    "code,status",
    [("DEPENDENCY_UNAVAILABLE", 503), ("AGENT_LIMIT_REACHED", 503), ("INTERNAL_ERROR", 500)],
)
def test_llm_failure_envelope(code, status):
    class Broken:
        def complete(self, *args, **kwargs):
            raise ToolError(code, "Fixed diagnostic")

    with TestClient(create_app(settings(), llm=Broken())) as client:
        result = client.post("/agent", json={"message": "query"}, headers=HEADERS)
    assert result.status_code == status
    assert result.json()["errors"][0]["code"] == code and result.json()["answer"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"llm_base_url": "http://user:secret@host"},
        {"llm_base_url": "file:///x"},
        {"llm_model": None},
        {"llm_model": " bad "},
    ],
)
def test_invalid_llm_configuration(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_llm_environment(monkeypatch):
    monkeypatch.setenv("LINESCOPE_LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("LINESCOPE_LLM_MODEL", "candidate")
    assert Settings.env().llm_model == "candidate"


@pytest.mark.skipif(
    not os.getenv("LINESCOPE_LIVE_LLM_MODEL"), reason="Opt-in live model verification"
)
def test_live_llm_http_and_postgres(seeded):
    llm = OllamaClient(
        base_url=os.environ["LINESCOPE_LIVE_LLM_URL"], model=os.environ["LINESCOPE_LIVE_LLM_MODEL"]
    )
    with TestClient(create_app(settings(), seeded, llm=llm)) as client:
        result = client.post(
            "/agent",
            json={
                "message": "設備コードM-204の現在のstate_codeを正本から取得し、コードも含めて教えて。"
            },
            headers=HEADERS,
        )
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "ok" and "STOPPED" in body["answer"] and "M-204" in body["answer"]
    assert any(
        item["tool"] == "get_equipment_state" and item["data"]["state_code"] == "STOPPED"
        for item in body["data"]["tool_results"]
    )
    assert body["evidence"]["tool_results"]
    with seeded.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "headers",
    [
        {**HEADERS, "Content-Type": "text/plain"},
        {**HEADERS, "Content-Type": "application/json", "Idempotency-Key": "invalid"},
        [
            ("Authorization", "Bearer token"),
            ("Content-Type", "application/json"),
            ("Idempotency-Key", str(UUID(int=1))),
            ("Idempotency-Key", str(UUID(int=2))),
        ],
    ],
)
def test_invalid_content_type_and_retry_header(headers):
    llm = ScriptedLLM()
    with TestClient(create_app(settings(), llm=llm)) as client:
        result = client.post("/agent", content='{"message":"query"}', headers=headers)
    assert result.status_code == 400 and not llm.requests


def test_partial_result_retains_evidence_and_warning(seeded):
    llm = ScriptedLLM(
        call("get_equipment_state"),
        call("get_equipment", {"equipment_id": str(UUID(int=999))}),
        LLMReply("取得できた結果のみです", ()),
    )
    with TestClient(create_app(settings(), seeded, llm=llm)) as client:
        result = client.post("/agent", json={"message": "設備を調べて"}, headers=HEADERS)
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "partial" and body["warnings"][0]["code"] == "TARGET_NOT_FOUND"
    assert len(body["data"]["tool_results"]) == len(body["evidence"]["tool_results"]) == 1
