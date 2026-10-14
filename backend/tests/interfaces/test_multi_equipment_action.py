"""Explicit multiple-target command through approval and atomic execution."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import column, func, select, table, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from interfaces.test_controlled_action_scenarios import approve_execute, counts, headers, query
from interfaces.test_equipment_prepare_api import world as world
from linescope.interfaces.api import create_app
from linescope.settings import Settings

MESSAGE = "設備[M-204,M-208]の状態を保全中に変更して"
STATE = table(
    "equipment_current_state",
    column("equipment_id", PGUUID()),
    column("state_code"),
    column("version"),
)


def client_for(world):
    return TestClient(
        create_app(
            Settings(
                users={
                    "requester": {"user_id": "maint1", "role": "maintenance"},
                    "approver": {"user_id": "maint2", "role": "maintenance"},
                    "production": {"user_id": "prod1", "role": "production"},
                }
            ),
            world,
        )
    )


def post(client, message=MESSAGE, **fields):
    return client.post("/agent", json={"message": message, **fields}, headers=headers())


def test_multiple_targets_approve_execute_and_response_retry_are_one_change(world):
    key = str(uuid4())
    with client_for(world) as client:
        before = query(world, select(STATE))
        response = client.post(
            "/agent", json={"message": MESSAGE}, headers={**headers(), "Idempotency-Key": key}
        )
        assert response.status_code == 200
        saved = response.json()["data"]
        assert len(saved["canonical_snapshot"]["targets"]) == 2
        assert query(world, select(STATE)) == before
        endpoint = f"/update-requests/{saved['update_request_id']}/execute"
        assert client.post(endpoint, headers=headers()).status_code == 409
        approve_execute(client, saved)
        assert all(row["state_code"] == "UNDER_MAINTENANCE" for row in query(world, select(STATE)))
        committed = counts(world)
        assert committed["business_update_history"] == 1
        assert committed["equipment_state_history"] == 2
        assert client.post(endpoint, headers=headers()).status_code == 200
        replay = client.post(
            "/agent", json={"message": MESSAGE}, headers={**headers(), "Idempotency-Key": key}
        )
        assert replay.status_code == 200
        assert replay.json()["data"]["update_request_id"] == saved["update_request_id"]
        assert replay.json()["data"]["canonical_snapshot"] == saved["canonical_snapshot"]
        assert counts(world) == committed


@pytest.mark.parametrize(
    "message,token,status",
    [
        ("設備[M-204,M-999]の状態を保全中に変更して", "requester", 404),
        ("設備[M-204,M-204]の状態を保全中に変更して", "requester", 422),
        ("設備[M-204,M-208]の状態を停止に変更して", "requester", 422),
        (MESSAGE, "production", 403),
        (
            "設備[" + ",".join(f"M-{n}" for n in range(11)) + "]の状態を停止に変更して",
            "requester",
            400,
        ),
    ],
)
def test_invalid_batch_rejects_all_targets_before_saving(world, message, token, status):
    before = query(world, select(STATE))
    with client_for(world) as client:
        response = client.post("/agent", json={"message": message}, headers=headers(token))
    assert response.status_code == status
    assert query(world, select(STATE)) == before
    assert (
        query(world, select(func.count().label("n")).select_from(table("update_request")))[0]["n"]
        == 0
    )
    assert counts(world)["business_update_history"] == 0


def test_one_stale_target_rejects_entire_execution(world):
    with client_for(world) as client:
        saved = post(client).json()["data"]
        assert (
            client.post(
                f"/approvals/{saved['approval_id']}/approve",
                json={"snapshot_hash": saved["snapshot_hash"]},
                headers=headers("approver"),
            ).status_code
            == 200
        )
        target = saved["canonical_snapshot"]["targets"][1]["target_id"]
        query(world, update(STATE).where(STATE.c.equipment_id == target).values(version=10))
        before = query(world, select(STATE))
        response = client.post(
            f"/update-requests/{saved['update_request_id']}/execute", headers=headers()
        )
        assert response.status_code == 409
        assert response.json()["errors"][0]["code"] == "VERSION_CONFLICT"
        assert query(world, select(STATE)) == before
        assert counts(world)["business_update_history"] == 0
        assert counts(world)["equipment_state_history"] == 0


def test_replacement_supersedes_the_whole_batch(world):
    with client_for(world) as client:
        old = post(client).json()["data"]
        response = post(
            client,
            "設備[M-204,M-208]の状態を不明に変更して",
            replace_update_request_id=old["update_request_id"],
        )
        assert response.status_code == 200
        saved = response.json()["data"]
        assert (
            client.get(f"/update-requests/{old['update_request_id']}", headers=headers()).json()[
                "data"
            ]["status"]
            == "INVALIDATED"
        )
        assert (
            client.post(
                f"/update-requests/{old['update_request_id']}/execute", headers=headers()
            ).status_code
            == 409
        )
        approve_execute(client, saved)
        assert all(row["state_code"] == "UNKNOWN" for row in query(world, select(STATE)))
        assert counts(world)["business_update_history"] == 1
