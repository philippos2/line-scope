"""Saved record CREATEs through human approval/execute APIs; Prepare stays internal."""

import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_maintenance_plan_approval_api import act, client_for, headers
from test_maintenance_prepare import prepare
from test_maintenance_record_create_approval import current, insert_conflict
from test_maintenance_record_create_approval import prepared as create_fixture

from linescope.api import create_app
from linescope.execute import MaintenanceRecordCreateExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError
from linescope.settings import Settings


@pytest.fixture
def world(db):
    return create_fixture.__wrapped__(db)


def count(db, table):
    queries = {
        "maintenance_record": "SELECT count(*) AS n FROM maintenance_record",
        "business_update_history": "SELECT count(*) AS n FROM business_update_history",
        "equipment_state_history": "SELECT count(*) AS n FROM equipment_state_history",
    }
    with db.transaction() as connection:
        return connection.execute(queries[table]).fetchone()["n"]


def execute(client, saved, token="requester", **kwargs):
    return client.post(
        f"/update-requests/{saved.update_request_id}/execute",
        headers=headers(token) if token else {},
        **kwargs,
    )


def test_inspect_approve_create_and_replay_separate_confirmed_from_current(world):
    db, _, saved = world
    with client_for(db) as client:
        inspected = client.get(f"/update-requests/{saved.update_request_id}", headers=headers())
        assert inspected.status_code == 200
        assert inspected.json()["data"]["canonical_snapshot"] == saved.snapshot.data
        assert act(client, saved, "approve").status_code == 200
        first = execute(client, saved)
        assert first.status_code == 200
        body = first.json()
        assert body["status"] == "ok" and body["warnings"] == body["errors"] == []
        assert body["context_id"] is None
        data = body["data"]
        assert data["update_request_id"] == str(saved.update_request_id)
        assert data["approval_id"] == str(saved.approval_id)
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["execution_result"]["targets"] == saved.snapshot.data["targets"]
        assert len(data["current_versions"]) == 2 and data["observed_at"]
        for observed, target in zip(
            data["current_snapshot"]["targets"], saved.snapshot.data["targets"], strict=True
        ):
            assert observed["snapshot"] == target["after"]
        assert all(
            item["version"] == item["confirmed_version"] == 1 and item["version_delta"] == 0
            for item in data["current_versions"]
        )
        with db.transaction() as connection:
            connection.execute(
                "UPDATE maintenance_record SET result='Revised observation',version=2 WHERE maintenance_record_id=%s",
                (saved.snapshot.data["targets"][0]["target_id"],),
            )
        replay = execute(client, saved).json()["data"]
        assert replay["execution_result"] == data["execution_result"]
        assert [item["version_delta"] for item in replay["current_versions"]] == [1, 0]
        assert (
            replay["current_snapshot"]["targets"][0]["snapshot"]["result"] == "Revised observation"
        )
        assert (
            replay["execution_result"]["targets"][0]["after"]["result"]
            == saved.snapshot.data["targets"][0]["after"]["result"]
        )
        inspected = client.get(
            f"/update-requests/{saved.update_request_id}", headers=headers("requester")
        )
        assert inspected.json()["data"]["execution_result"] == data["execution_result"]
    assert count(db, "maintenance_record") == 2 and count(db, "business_update_history") == 1
    assert count(db, "equipment_state_history") == 0


@pytest.mark.parametrize("action", ["approve", "execute"])
@pytest.mark.parametrize("id_conflict", [False, True])
def test_create_conflict_is_409_and_invalidates_entire_request(world, action, id_conflict):
    db, _, saved = world
    with client_for(db) as client:
        if action == "execute":
            assert act(client, saved, "approve").status_code == 200
        insert_conflict(db, saved, id_conflict=id_conflict)
        result = act(client, saved, "approve") if action == "approve" else execute(client, saved)
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == "CREATE_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert count(db, "maintenance_record") == 1 and count(db, "business_update_history") == 0


@pytest.mark.parametrize(
    "token,status", [(None, 401), ("floor", 403), ("production", 403), ("requester", 403)]
)
def test_approval_authentication_role_and_self_approval(world, token, status):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve", token).status_code == status
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("token,status", [(None, 401), ("approver", 403), ("manager", 403)])
def test_only_original_requester_can_execute_create(world, token, status):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, token).status_code == status
    assert current(db, saved)["status"] == "APPROVED"
    assert count(db, "maintenance_record") == 0


def test_wrong_hash_and_injected_create_values_do_not_change_saved_request(world):
    db, _, saved = world
    with client_for(db) as client:
        result = act(client, saved, "approve", snapshot_hash="0" * 64)
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == "APPROVAL_HASH_MISMATCH"
        assert act(client, saved, "approve").status_code == 200
        result = execute(client, saved, json={"record_code": "INJECTED", "equipment_id": "other"})
        assert result.status_code == 400
    assert current(db, saved)["canonical_snapshot"] == saved.snapshot.data
    assert current(db, saved)["status"] == "APPROVED"


@pytest.mark.parametrize("unexpected", [False, True])
def test_current_read_failure_keeps_confirmed_result_and_returns_partial(
    world, monkeypatch, unexpected
):
    db, _, saved = world

    def fail(self, result):
        if unexpected:
            raise RuntimeError("private-secret")
        raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-secret")

    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        monkeypatch.setattr(MaintenanceRecordCreateExecute, "observe_current", fail)
        result = execute(client, saved)
        body = result.json()
        assert result.status_code == 200 and body["status"] == "partial"
        data = body["data"]
        assert data["status"] == "COMPLETED" and data["execution_result"]["history_id"]
        assert data["current_snapshot"] is data["current_versions"] is data["observed_at"] is None
        assert body["warnings"][0]["code"] == (
            "INTERNAL_ERROR" if unexpected else "DEPENDENCY_UNAVAILABLE"
        )
        assert body["errors"] == [] and "private-secret" not in result.text
        assert execute(client, saved).json()["data"]["execution_result"] == data["execution_result"]
    assert current(db, saved)["status"] == "COMPLETED"


def test_deleted_current_target_is_partial_not_a_failed_execution(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        confirmed = execute(client, saved).json()["data"]["execution_result"]
        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM maintenance_record WHERE maintenance_record_id=%s",
                (saved.snapshot.data["targets"][0]["target_id"],),
            )
        replay = execute(client, saved)
        assert replay.status_code == 200 and replay.json()["status"] == "partial"
        assert replay.json()["warnings"][0]["code"] == "TARGET_NOT_FOUND"
        assert replay.json()["data"]["execution_result"] == confirmed
    assert current(db, saved)["status"] == "COMPLETED"


def test_completed_owner_replay_survives_current_permission_loss(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        confirmed = execute(client, saved).json()["data"]["execution_result"]
    settings = Settings(users={"requester": {"user_id": "maintenance1", "role": "floor"}})
    with TestClient(create_app(settings, db, EventLogger(stream=io.StringIO()))) as client:
        replay = execute(client, saved)
        assert replay.status_code == 200
        assert replay.json()["data"]["execution_result"] == confirmed
    assert count(db, "maintenance_record") == 2 and count(db, "business_update_history") == 1


def test_parallel_http_create_replays_one_durable_result(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.map(lambda _: execute(client, saved), range(2))
        assert first.status_code == second.status_code == 200
        assert first.json()["data"]["execution_result"] == second.json()["data"]["execution_result"]
    assert count(db, "maintenance_record") == 2 and count(db, "business_update_history") == 1


@pytest.mark.parametrize("action", ["approve", "execute"])
def test_mixed_plan_and_record_approval_supported_but_execution_deferred(world, action):
    db, service, _ = world
    saved = prepare(service)
    with client_for(db) as client:
        result = act(client, saved, "approve") if action == "approve" else execute(client, saved)
        assert result.status_code == (200 if action == "approve" else 400)
        if action == "execute":
            assert result.json()["errors"][0]["code"] == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == (
        "APPROVED" if action == "approve" else "WAITING_APPROVAL"
    )


@pytest.mark.parametrize("fault", ["missing", "mismatch"])
def test_reference_failure_is_422_and_invalidates_all_records(world, fault):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        plan_id = next(
            t["after"]["maintenance_plan_id"]
            for t in saved.snapshot.data["targets"]
            if t["after"]["maintenance_plan_id"] is not None
        )
        with db.transaction() as connection:
            if fault == "missing":
                connection.execute(
                    "DELETE FROM maintenance_plan WHERE maintenance_plan_id=%s", (plan_id,)
                )
            else:
                connection.execute(
                    "UPDATE maintenance_plan SET equipment_id=%s WHERE maintenance_plan_id=%s",
                    ("00000000-0000-0000-0000-00000000000b", plan_id),
                )
        result = execute(client, saved)
        assert result.status_code == 422
        assert result.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert count(db, "maintenance_record") == count(db, "business_update_history") == 0


def test_rejected_record_request_cannot_execute_or_be_approved_again(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "reject").status_code == 200
        for result in (execute(client, saved), act(client, saved, "approve")):
            assert result.status_code == 409
            assert result.json()["errors"][0]["code"] == "INVALID_UPDATE_STATE"
    assert current(db, saved)["status"] == "REJECTED"
    assert count(db, "maintenance_record") == count(db, "business_update_history") == 0


def test_expired_record_approval_is_410_without_record_inserts(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as connection:
            connection.execute(
                "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',"
                "expires_at=statement_timestamp()-interval '1 minute' WHERE approval_id=%s",
                (saved.approval_id,),
            )
        result = execute(client, saved)
        assert result.status_code == 410
        assert result.json()["errors"][0]["code"] == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED"
    assert count(db, "maintenance_record") == count(db, "business_update_history") == 0
