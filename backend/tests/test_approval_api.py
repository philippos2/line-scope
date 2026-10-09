import io
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_equipment_prepare_api import MESSAGE
from test_read_agent import ScriptedLLM

from linescope.api import create_app
from linescope.demo_seed import DEMO_EQUIPMENT, seed_demo
from linescope.logging import EventLogger
from linescope.settings import Settings


@pytest.fixture
def world(db):
    db.migrate()
    seed_demo(db)
    return db


def client_for(db, stream=None):
    settings = Settings(
        users={
            "requester": {"user_id": "requester", "role": "maintenance"},
            "approver": {"user_id": "approver", "role": "maintenance"},
            "floor": {"user_id": "floor", "role": "floor"},
            "manager": {"user_id": "manager", "role": "manager"},
        }
    )
    return TestClient(
        create_app(settings, db, EventLogger(stream=stream or io.StringIO()), llm=ScriptedLLM())
    )


def headers(token="approver"):
    return {"Authorization": f"Bearer {token}"}


def prepare(client, token="requester"):
    result = client.post("/agent", json={"message": MESSAGE}, headers=headers(token))
    assert result.status_code == 200
    return result.json()["data"]


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_prepare_inspect_human_action_contract(world, action):
    stream = io.StringIO()
    with client_for(world, stream) as client:
        saved = prepare(client)
        inspected = client.get(f"/update-requests/{saved['update_request_id']}", headers=headers())
        assert inspected.status_code == 200
        kwargs = (
            {"json": {"snapshot_hash": inspected.json()["data"]["snapshot_hash"]}}
            if action == "approve"
            else {}
        )
        result = client.post(
            f"/approvals/{saved['approval_id']}/{action}", headers=headers(), **kwargs
        )
        assert result.status_code == 200
        body = result.json()
        assert body["status"] == "ok" and body["context_id"] is None
        assert body["errors"] == []
        data = body["data"]
        assert data["update_request_id"] == saved["update_request_id"]
        assert data["approval_id"] == saved["approval_id"]
        assert (
            data["status"]
            == data["approval_status"]
            == ("APPROVED" if action == "approve" else "REJECTED")
        )
        if action == "approve":
            assert datetime.fromisoformat(data["expires_at"]) - datetime.fromisoformat(
                data["approved_at"]
            ) == timedelta(minutes=30)
        else:
            assert data["approved_at"] is data["expires_at"] is None
        retry = client.post(
            f"/approvals/{saved['approval_id']}/{action}", headers=headers(), **kwargs
        )
        assert (
            retry.status_code == 409 and retry.json()["errors"][0]["code"] == "INVALID_UPDATE_STATE"
        )
    with world.transaction() as c:
        assert (
            c.execute(
                "SELECT state_code FROM equipment_current_state WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            ).fetchone()["state_code"]
            == "STOPPED"
        )
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    operation = next(
        e for e in events if e["event"] == "approval.completed" and e["outcome"] == "success"
    )
    assert operation["request_id"] == body["request_id"] and operation["actor_id"] == "approver"


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(
    "token,status", [(None, 401), ("floor", 403), ("requester", 403), ("manager", 200)]
)
def test_authentication_role_and_self_approval(world, action, token, status):
    with client_for(world) as client:
        saved = prepare(client, "manager" if token == "manager" else "requester")
        kwargs = {"json": {"snapshot_hash": saved["snapshot_hash"]}} if action == "approve" else {}
        result = client.post(
            f"/approvals/{saved['approval_id']}/{action}",
            headers=headers(token) if token else {},
            **kwargs,
        )
        assert result.status_code == status


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"null",
        b"[]",
        b"{}",
        b'{"snapshot_hash":1}',
        b'{"snapshot_hash":null}',
        b'{"snapshot_hash":"x"}',
        b'{"snapshot_hash":"x","actor_id":"manager"}',
        b'{"snapshot_hash":"x","snapshot_hash":"y"}',
        b'{"snapshot_hash":"x","state_code":"RUNNING"}',
    ],
)
def test_approve_rejects_invalid_or_injected_fields(world, body):
    with client_for(world) as client:
        saved = prepare(client)
        result = client.post(
            f"/approvals/{saved['approval_id']}/approve",
            content=body,
            headers={**headers(), "Content-Type": "application/json"},
        )
        assert result.status_code == 400
        assert result.json()["errors"][0]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", b'{"user_id":"manager"}'])
def test_reject_requires_empty_body(world, body):
    with client_for(world) as client:
        saved = prepare(client)
        result = client.post(
            f"/approvals/{saved['approval_id']}/reject", content=body, headers=headers()
        )
        assert result.status_code == 400


def test_hash_mismatch_and_version_conflict_are_409(world):
    with client_for(world) as client:
        saved = prepare(client)
        endpoint = f"/approvals/{saved['approval_id']}/approve"
        mismatch = client.post(endpoint, json={"snapshot_hash": "0" * 64}, headers=headers())
        assert (
            mismatch.status_code == 409
            and mismatch.json()["errors"][0]["code"] == "APPROVAL_HASH_MISMATCH"
        )
        with world.transaction() as c:
            c.execute(
                "UPDATE equipment_current_state SET version=2 WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            )
        conflict = client.post(
            endpoint, json={"snapshot_hash": saved["snapshot_hash"]}, headers=headers()
        )
        assert (
            conflict.status_code == 409
            and conflict.json()["errors"][0]["code"] == "VERSION_CONFLICT"
        )
        current = client.get(
            f"/update-requests/{saved['update_request_id']}", headers=headers()
        ).json()["data"]
        assert current["status"] == current["approval_status"] == "INVALIDATED"


@pytest.mark.parametrize("identifier,expected", [("bad", 400), (str(uuid4()), 404)])
def test_invalid_and_missing_approval_ids(world, identifier, expected):
    with client_for(world) as client:
        result = client.post(f"/approvals/{identifier}/reject", headers=headers())
        assert result.status_code == expected


def test_approve_requires_json_content_type(world):
    with client_for(world) as client:
        saved = prepare(client)
        result = client.post(
            f"/approvals/{saved['approval_id']}/approve",
            content=json.dumps({"snapshot_hash": saved["snapshot_hash"]}),
            headers=headers(),
        )
        assert result.status_code == 400


def test_audit_failure_returns_sanitized_500_and_leaves_request_pending(world):
    stream = io.StringIO()
    with client_for(world, stream) as client:
        saved = prepare(client)
        with world.transaction() as c:
            c.execute("""CREATE FUNCTION reject_http_audit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'private-secret'; END $$""")
            c.execute(
                "CREATE TRIGGER reject_http_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_http_audit()"
            )
        result = client.post(
            f"/approvals/{saved['approval_id']}/approve",
            json={"snapshot_hash": saved["snapshot_hash"]},
            headers=headers(),
        )
        assert result.status_code == 500
        assert result.json()["errors"][0]["code"] == "INTERNAL_ERROR"
        current = client.get(
            f"/update-requests/{saved['update_request_id']}", headers=headers()
        ).json()["data"]
        assert current["status"] == "WAITING_APPROVAL" and current["approval_status"] == "PENDING"
        assert "private-secret" not in result.text and "private-secret" not in stream.getvalue()
