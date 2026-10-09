from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_proposals import category_snapshot, context, save

from linescope.api import create_app
from linescope.settings import Settings


@pytest.fixture
def stored(db):
    db.migrate()
    from linescope.proposals import ProposalStore

    return db, ProposalStore(db)


def client_for(db, user, role):
    return TestClient(create_app(Settings(users={"token": {"user_id": user, "role": role}}), db))


@pytest.mark.parametrize("category", ["equipment", "maintenance", "production", "dependency"])
@pytest.mark.parametrize("role", ["floor", "maintenance", "production", "manager"])
def test_visibility_matrix(stored, category, role):
    db, store = stored
    owner = context("owner", "manager")
    saved = save(store, category_snapshot(category, owner), owner)
    permitted = (
        role == "manager"
        or (role == "maintenance" and category in {"equipment", "maintenance"})
        or (role == "production" and category == "production")
    )
    with client_for(db, "reader", role) as client:
        result = client.get(
            f"/update-requests/{saved.update_request_id}", headers={"Authorization": "Bearer token"}
        )
    assert result.status_code == (200 if permitted else 403)
    if permitted:
        data = result.json()["data"]
        assert data["canonical_snapshot"] == saved.snapshot.data
        assert data["snapshot_hash"] == saved.snapshot.snapshot_hash
        assert data["approval_id"] == str(saved.approval_id)
        assert data["status"] == "WAITING_APPROVAL"
        assert data["approved_at"] is None and data["expires_at"] is None
        assert data["snapshot_schema_version"] == 1
    else:
        assert result.json()["data"] == {}
        assert saved.snapshot.snapshot_hash not in result.text


@pytest.mark.parametrize("role", ["floor", "maintenance", "production", "manager"])
def test_owner_visibility_survives_role_change_without_source_create(stored, role):
    db, store = stored
    owner = context("owner", "manager")
    saved = save(store, category_snapshot("dependency", owner), owner)
    with client_for(db, "owner", role) as client:
        result = client.get(
            f"/update-requests/{saved.update_request_id}", headers={"Authorization": "Bearer token"}
        )
    assert result.status_code == 200
    assert result.json()["data"]["canonical_snapshot"] == saved.snapshot.data
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM dependency_relation").fetchone()["n"] == 0
        )
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 1


@pytest.mark.parametrize("identity,status", [("invalid", 400), (str(uuid4()), 404)])
def test_invalid_and_missing_ids(stored, identity, status):
    db, _ = stored
    with client_for(db, "reader", "manager") as client:
        result = client.get(
            f"/update-requests/{identity}", headers={"Authorization": "Bearer token"}
        )
    assert result.status_code == status


def test_unauthenticated_does_not_access_database():
    class NoDatabase:
        def transaction(self):
            raise AssertionError("Must authenticate first")

    with client_for(NoDatabase(), "owner", "manager") as client:
        result = client.get(f"/update-requests/{uuid4()}")
    assert result.status_code == 401


def test_corrupt_snapshot_is_not_returned(stored):
    db, store = stored
    saved = save(store)
    with db.transaction() as connection:
        connection.execute("UPDATE update_request SET snapshot_hash=%s", ("a" * 64,))
    with client_for(db, "floor1", "floor") as client:
        result = client.get(
            f"/update-requests/{saved.update_request_id}", headers={"Authorization": "Bearer token"}
        )
    assert result.status_code == 500
    assert result.json()["data"] == {}


def test_approved_times_and_snapshot_remain_stored_facts(stored):
    from datetime import timedelta
    from uuid import UUID

    from test_proposals import NOW

    db, store = stored
    saved = save(store)
    with db.transaction() as connection:
        connection.execute("UPDATE update_request SET status='APPROVED'")
        connection.execute(
            "UPDATE approval SET status='APPROVED', approver_id='manager', approved_at=%s, expires_at=%s",
            (NOW, NOW + timedelta(minutes=30)),
        )
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'EQ','Machine','machine',true)",
            (UUID(int=1),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code,version) VALUES(%s,'UNKNOWN',9)",
            (UUID(int=1),),
        )
    with client_for(db, "floor1", "floor") as client:
        result = client.get(
            f"/update-requests/{saved.update_request_id}", headers={"Authorization": "Bearer token"}
        )
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["status"] == data["approval_status"] == "APPROVED"
    assert data["approved_at"] == "2026-10-09T00:00:00.000000Z"
    assert data["expires_at"] == "2026-10-09T00:30:00.000000Z"
    assert data["canonical_snapshot"] == saved.snapshot.data
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT status FROM update_request").fetchone()["status"]
            == "APPROVED"
        )
        assert (
            connection.execute("SELECT state_code FROM equipment_current_state").fetchone()[
                "state_code"
            ]
            == "UNKNOWN"
        )


@pytest.mark.parametrize(
    "kind,code",
    [
        ("connection", "DEPENDENCY_UNAVAILABLE"),
        ("timeout", "RESOURCE_BUSY"),
        ("internal", "INTERNAL_ERROR"),
    ],
)
def test_storage_failure_envelope_is_sanitized(kind, code):
    from contextlib import contextmanager

    import psycopg

    class Broken:
        @contextmanager
        def transaction(self):
            error = {
                "connection": psycopg.OperationalError,
                "timeout": psycopg.errors.QueryCanceled,
                "internal": psycopg.errors.UndefinedTable,
            }[kind]
            raise error("private password SQL")
            yield

    with client_for(Broken(), "reader", "manager") as client:
        result = client.get(
            f"/update-requests/{uuid4()}", headers={"Authorization": "Bearer token"}
        )
    assert result.status_code == (500 if kind == "internal" else 503)
    assert result.json()["errors"][0]["code"] == code
    assert "private" not in result.text and "password" not in result.text
