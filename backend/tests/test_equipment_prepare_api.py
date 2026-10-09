from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_read_agent import ScriptedLLM, call

from linescope.api import create_app
from linescope.demo_seed import DEMO_EQUIPMENT, seed_demo
from linescope.llm import LLMReply
from linescope.proposals import ProposalError, ProposalStore
from linescope.settings import Settings

MESSAGE = "設備M-204の状態をRUNNINGに変更して"
HEADERS = {"Authorization": "Bearer token"}


@pytest.fixture
def world(db):
    db.migrate()
    seed_demo(db)
    return db


def settings(role="floor"):
    return Settings(users={"token": {"user_id": "user1", "role": role}})


def test_explicit_command_creates_pending_snapshot_without_llm_or_state_change(world):
    llm = ScriptedLLM()
    with TestClient(create_app(settings(), world, llm=llm)) as client:
        result = client.post("/agent", json={"message": MESSAGE}, headers=HEADERS)
        data = result.json()["data"]
        viewed = client.get("/update-requests/" + data["update_request_id"], headers=HEADERS)
    assert result.status_code == 200 and result.json()["status"] == "ok"
    assert not llm.requests and viewed.json()["data"] == data
    assert data["status"] == "WAITING_APPROVAL" and data["approval_status"] == "PENDING"
    assert data["approved_at"] is None and data["expires_at"] is None
    target = data["canonical_snapshot"]["targets"][0]
    assert (
        target["before"]["state_code"] == "STOPPED" and target["after"]["state_code"] == "RUNNING"
    )
    assert "現在状態は変更していません" in result.json()["answer"]
    with world.transaction() as connection:
        assert (
            connection.execute(
                "SELECT state_code FROM equipment_current_state WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            ).fetchone()["state_code"]
            == "STOPPED"
        )


def test_prepare_works_when_llm_is_unconfigured_and_retry_keeps_snapshot(world):
    key = str(uuid4())
    headers = {**HEADERS, "Idempotency-Key": key}
    with TestClient(create_app(settings(), world)) as client:
        first = client.post("/agent", json={"message": MESSAGE}, headers=headers)
        with world.transaction() as connection:
            connection.execute("UPDATE equipment_current_state SET state_code='UNKNOWN',version=9")
        retry = client.post("/agent", json={"message": MESSAGE}, headers=headers)
        mismatch = client.post(
            "/agent", json={"message": "M-208の状態を停止に変更して"}, headers=headers
        )
    assert first.status_code == retry.status_code == 200
    assert first.json()["data"] == retry.json()["data"]
    assert first.json()["request_id"] != retry.json()["request_id"]
    assert (
        mismatch.status_code == 409 and mismatch.json()["errors"][0]["code"] == "DUPLICATE_REQUEST"
    )


@pytest.mark.parametrize(
    "message,status,code",
    [
        (MESSAGE, 403, "AUTHORIZATION_DENIED"),
        ("M-999の状態を停止に変更して", 404, "TARGET_NOT_FOUND"),
        ("M-204の状態を停止に変更して", 422, "BUSINESS_RULE_VIOLATION"),
    ],
)
def test_prepare_rejections_are_mapped_and_never_save(world, message, status, code):
    with TestClient(
        create_app(settings("production" if status == 403 else "floor"), world)
    ) as client:
        result = client.post("/agent", json={"message": message}, headers=HEADERS)
    assert result.status_code == status and result.json()["errors"][0]["code"] == code
    with world.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "message",
    [
        "『" + MESSAGE + "』",
        "設備M-204の状態をRUNNINGに変更しないで",
        MESSAGE + "？",
        MESSAGE + "、M-208も変更して",
    ],
)
def test_unsupported_intent_stays_read_only_even_when_llm_asks_to_prepare(world, message):
    llm = ScriptedLLM(
        call(
            "prepare_equipment_state_update",
            {"equipment_id": str(DEMO_EQUIPMENT[0][0]), "state_code": "RUNNING"},
        ),
        LLMReply("実行しました", ()),
    )
    with TestClient(create_app(settings(), world, llm=llm)) as client:
        result = client.post("/agent", json={"message": message}, headers=HEADERS)
    assert (
        result.status_code == 403 and result.json()["errors"][0]["code"] == "AUTHORIZATION_DENIED"
    )
    assert "prepare_equipment_state_update" not in llm.requests[0][1]
    with world.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


def test_response_read_failure_preserves_saved_ids_and_allows_retry(world, monkeypatch):
    original = ProposalStore.get

    def fail(*args):
        raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-dsn-secret")

    key = str(uuid4())
    with TestClient(create_app(settings(), world)) as client:
        monkeypatch.setattr(ProposalStore, "get", fail)
        result = client.post(
            "/agent", json={"message": MESSAGE}, headers={**HEADERS, "Idempotency-Key": key}
        )
        assert result.status_code == 503 and result.json()["data"]["status"] == "WAITING_APPROVAL"
        assert "private-dsn-secret" not in result.text
        monkeypatch.setattr(ProposalStore, "get", original)
        retry = client.post(
            "/agent", json={"message": MESSAGE}, headers={**HEADERS, "Idempotency-Key": key}
        )
    assert retry.status_code == 200
    assert result.json()["data"]["update_request_id"] == retry.json()["data"]["update_request_id"]


def test_prepare_requires_authentication(world):
    with TestClient(create_app(settings(), world)) as client:
        result = client.post("/agent", json={"message": MESSAGE})
    assert result.status_code == 401


def test_explicit_replacement_invalidates_only_the_owned_old_request(world):
    configured = settings()
    configured.users["other"] = {"user_id": "other", "role": "floor"}
    with TestClient(create_app(configured, world)) as client:
        first = client.post("/agent", json={"message": MESSAGE}, headers=HEADERS).json()["data"]
        body = {
            "message": "M-204の状態をUNKNOWNに変更して",
            "replace_update_request_id": first["update_request_id"],
        }
        denied = client.post("/agent", json=body, headers={"Authorization": "Bearer other"})
        assert denied.status_code == 403
        second = client.post("/agent", json=body, headers=HEADERS)
        old = client.get("/update-requests/" + first["update_request_id"], headers=HEADERS)
        invalid = client.post("/agent", json=body, headers=HEADERS)
    assert second.status_code == 200 and old.json()["data"]["status"] == "INVALIDATED"
    assert (
        second.json()["data"]["canonical_snapshot"]["supersedes_update_request_id"]
        == first["update_request_id"]
    )
    assert (
        invalid.status_code == 409 and invalid.json()["errors"][0]["code"] == "INVALID_UPDATE_STATE"
    )
