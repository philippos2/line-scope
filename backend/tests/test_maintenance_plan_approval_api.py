"""HTTP admission of saved maintenance plan UPDATEs; Prepare remains internal."""

import io
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_maintenance_prepare import identity, prepare, update
from test_maintenance_prepare import service as maintenance_fixture
from test_production_prepare import prepare as prepare_production
from test_production_prepare import service as production_fixture

from linescope.api import create_app
from linescope.logging import EventLogger
from linescope.proposals import ProposalStore
from linescope.settings import Settings


@pytest.fixture
def world(db):
    db, service = maintenance_fixture.__wrapped__(db)
    return db, service, prepare(service, [update(), update(21)])


def headers(token="approver"):
    return {"Authorization": f"Bearer {token}"}


def client_for(db):
    return TestClient(
        create_app(
            Settings(
                users={
                    "requester": {"user_id": "maintenance1", "role": "maintenance"},
                    "approver": {"user_id": "approver", "role": "maintenance"},
                    "floor": {"user_id": "floor", "role": "floor"},
                    "production": {"user_id": "production", "role": "production"},
                    "manager": {"user_id": "manager", "role": "manager"},
                }
            ),
            db,
            EventLogger(stream=io.StringIO()),
        )
    )


def act(client, saved, action, token="approver", snapshot_hash=None):
    return client.post(
        f"/approvals/{saved.approval_id}/{action}",
        headers=headers(token) if token else {},
        **(
            {"json": {"snapshot_hash": snapshot_hash or saved.snapshot.snapshot_hash}}
            if action == "approve"
            else {}
        ),
    )


def current(db, saved):
    return ProposalStore(db).get(identity(), str(saved.update_request_id))


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_saved_plan_snapshot_can_be_inspected_and_acted_on(world, action):
    db, _, saved = world
    with client_for(db) as client:
        inspected = client.get(f"/update-requests/{saved.update_request_id}", headers=headers())
        assert inspected.status_code == 200
        assert inspected.json()["data"]["canonical_snapshot"] == saved.snapshot.data
        result = act(client, saved, action)
        assert result.status_code == 200
        body = result.json()
        assert body["status"] == "ok" and body["errors"] == []
        assert body["context_id"] is None
        data = body["data"]
        assert data["update_request_id"] == str(saved.update_request_id)
        assert data["approval_id"] == str(saved.approval_id)
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
        retry = act(client, saved, action)
        assert retry.status_code == 409
        assert retry.json()["errors"][0]["code"] == "INVALID_UPDATE_STATE"
        assert current(db, saved)["expires_at"] == (
            datetime.fromisoformat(data["expires_at"]) if action == "approve" else None
        )
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT plan_status,version FROM maintenance_plan ORDER BY maintenance_plan_id"
            ).fetchall()
            == [{"plan_status": "PLANNED", "version": 5}] * 2
        )
        audit = connection.execute(
            "SELECT * FROM update_audit_event WHERE action=%s", (action.upper(),)
        ).fetchone()
        assert audit["actor_id"] == "approver" and audit["details"] == {"target_count": 2}
        assert str(audit["request_id"]) == body["request_id"]


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(
    "token,status",
    [(None, 401), ("floor", 403), ("production", 403), ("requester", 403), ("manager", 200)],
)
def test_current_roles_and_manager_only_self_approval(world, action, token, status):
    db, service, saved = world
    if token == "manager":
        saved = prepare(service, [update(), update(21)], context=identity("manager", "manager"))
    with client_for(db) as client:
        result = act(client, saved, action, token)
        assert result.status_code == status
    if status != 200:
        assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_wrong_hash_does_not_invalidate_but_one_changed_plan_invalidates_all(world):
    db, _, saved = world
    with client_for(db) as client:
        result = act(client, saved, "approve", snapshot_hash="0" * 64)
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == "APPROVAL_HASH_MISMATCH"
        assert current(db, saved)["status"] == "WAITING_APPROVAL"
        with db.transaction() as connection:
            connection.execute(
                "UPDATE maintenance_plan SET version=6 WHERE maintenance_plan_id=%s",
                (UUID(int=21),),
            )
        result = act(client, saved, "approve")
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_create_and_record_targets_are_not_silently_admitted(world, action):
    db, service, _ = world
    saved = prepare(service)
    with client_for(db) as client:
        result = act(client, saved, action)
        assert result.status_code == 400
        assert result.json()["errors"][0]["code"] == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_audit_storage_failure_rolls_back_approval_and_is_sanitized(world):
    db, _, saved = world
    with db.transaction() as connection:
        connection.execute("""CREATE FUNCTION fail_plan_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private-secret'; END $$""")
        connection.execute(
            "CREATE TRIGGER fail_plan_audit BEFORE INSERT ON update_audit_event "
            "FOR EACH ROW EXECUTE FUNCTION fail_plan_audit()"
        )
    with client_for(db) as client:
        result = act(client, saved, "approve")
        assert result.status_code == 500
        assert result.json()["errors"][0]["code"] == "INTERNAL_ERROR"
        assert "private-secret" not in result.text
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_other_categories_stay_outside_http_approval_scope(db, action):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare_production(service)
    with client_for(db) as client:
        result = act(client, saved, action, "manager")
        assert result.status_code == 400
        assert result.json()["errors"][0]["code"] == "INVALID_ARGUMENT"
    assert (
        ProposalStore(db).get(identity("manager", "manager"), str(saved.update_request_id))[
            "status"
        ]
        == "WAITING_APPROVAL"
    )


def test_maintenance_execute_http_connection_is_still_deferred(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        result = client.post(
            f"/update-requests/{saved.update_request_id}/execute", headers=headers("requester")
        )
        assert result.status_code == 400
        assert result.json()["errors"][0]["code"] == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "APPROVED"
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"]
            == 0
        )
