"""Human schedule APIs preserve confirmed results and observe current values separately."""

import io
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_maintenance_plan_approval_api import act, headers
from test_maintenance_record_create_api import execute
from test_production_schedule_approval import business, current
from test_production_schedule_approval import world as production_fixture

from linescope.api import create_app
from linescope.execute import ProductionScheduleExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError
from linescope.settings import Settings


@pytest.fixture
def world(db):
    return production_fixture.__wrapped__(db)


def client_for(db):
    settings = Settings(
        users={
            "requester": {"user_id": "production1", "role": "production"},
            "approver": {"user_id": "approver", "role": "production"},
            "maintenance": {"user_id": "maintenance", "role": "maintenance"},
            "floor": {"user_id": "floor", "role": "floor"},
            "manager": {"user_id": "manager", "role": "manager"},
        }
    )
    return TestClient(create_app(settings, db, EventLogger(stream=io.StringIO())))


def test_inspection_approval_execution_replay_and_current_version_difference(world):
    db, _, saved = world
    assignments = business(db)["assignments"]
    with client_for(db) as client:
        viewed = client.get(
            f"/update-requests/{saved.update_request_id}", headers=headers("requester")
        )
        assert (
            viewed.status_code == 200
            and viewed.json()["data"]["canonical_snapshot"] == saved.snapshot.data
        )
        assert act(client, saved, "approve").status_code == 200
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "ok"
        data = response.json()["data"]
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["execution_result"]["targets"] == saved.snapshot.data["targets"]
        assert data["observed_at"]
        for observed, target in zip(
            data["current_snapshot"]["targets"], saved.snapshot.data["targets"], strict=True
        ):
            assert observed["snapshot"] == target["after"]
        assert all(
            v["version"] == v["confirmed_version"] == 8 and v["version_delta"] == 0
            for v in data["current_versions"]
        )
        with db.transaction() as c:
            c.execute(
                "UPDATE production_operation SET planned_status='PLANNED',version=9 WHERE production_operation_id=%s",
                (UUID(int=20),),
            )
        replay = execute(client, saved).json()["data"]
        assert replay["execution_result"] == data["execution_result"]
        assert [v["version_delta"] for v in replay["current_versions"]] == [1, 0]
        assert replay["current_snapshot"]["targets"][0]["snapshot"]["planned_status"] == "PLANNED"
        assert replay["execution_result"]["targets"][0]["after"]["planned_status"] == "CANCELLED"
        assert (
            client.get(
                f"/update-requests/{saved.update_request_id}", headers=headers("requester")
            ).json()["data"]["execution_result"]
            == data["execution_result"]
        )
    assert business(db)["assignments"] == assignments


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(
    "token,status", [(None, 401), ("floor", 403), ("maintenance", 403), ("requester", 403)]
)
def test_approval_authentication_category_and_self_approval(world, action, token, status):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, action, token).status_code == status
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("token,status", [(None, 401), ("approver", 403), ("manager", 403)])
def test_execute_requires_original_requester(world, token, status):
    db, _, saved = world
    before = business(db)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, token).status_code == status
    assert current(db, saved)["status"] == "APPROVED" and business(db) == before


def test_wrong_hash_and_execution_value_injection_are_rejected(world):
    db, _, saved = world
    with client_for(db) as client:
        response = act(client, saved, "approve", snapshot_hash="0" * 64)
        assert (
            response.status_code == 409
            and response.json()["errors"][0]["code"] == "APPROVAL_HASH_MISMATCH"
        )
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, json={"planned_status": "PLANNED"}).status_code == 400
    assert current(db, saved)["status"] == "APPROVED"


@pytest.mark.parametrize("phase", ["approve", "execute"])
def test_version_conflict_is_409_and_retires_whole_request(world, phase):
    db, _, saved = world
    with client_for(db) as client:
        if phase == "execute":
            assert act(client, saved, "approve").status_code == 200
        with db.transaction() as c:
            c.execute(
                "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
                (UUID(int=21),),
            )
        before = business(db)
        response = act(client, saved, "approve") if phase == "approve" else execute(client, saved)
        assert (
            response.status_code == 409
            and response.json()["errors"][0]["code"] == "VERSION_CONFLICT"
        )
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before


@pytest.mark.parametrize("unexpected", [False, True])
def test_current_observation_failure_keeps_durable_result(world, monkeypatch, unexpected):
    db, _, saved = world

    def fail(self, result):
        if unexpected:
            raise RuntimeError("private-secret")
        raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-secret")

    monkeypatch.setattr(ProductionScheduleExecute, "observe_current", fail)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        data = response.json()["data"]
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["current_snapshot"] is data["current_versions"] is data["observed_at"] is None
        assert response.json()["warnings"][0]["code"] == (
            "INTERNAL_ERROR" if unexpected else "DEPENDENCY_UNAVAILABLE"
        )
        assert "private-secret" not in response.text
        assert execute(client, saved).json()["data"]["execution_result"] == data["execution_result"]


def test_deleted_current_target_returns_partial_without_changing_completion(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        confirmed = execute(client, saved).json()["data"]["execution_result"]
        with db.transaction() as c:
            c.execute(
                "DELETE FROM production_operation WHERE production_operation_id=%s", (UUID(int=21),)
            )
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        assert response.json()["warnings"][0]["code"] == "TARGET_NOT_FOUND"
        assert response.json()["data"]["execution_result"] == confirmed
    assert current(db, saved)["status"] == "COMPLETED"


def test_rejection_prevents_execution(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "reject").status_code == 200
        assert execute(client, saved).status_code == 409
    assert current(db, saved)["status"] == "REJECTED"


def test_parallel_http_execution_replays_one_result(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda _: execute(client, saved), range(2)))
        assert all(r.status_code == 200 for r in responses)
        assert (
            responses[0].json()["data"]["execution_result"]
            == responses[1].json()["data"]["execution_result"]
        )


def test_assignment_request_requires_approval_then_routes_to_assignment_execute(db):
    from test_production_assignment_prepare import prepare
    from test_production_assignment_prepare import service as assignment_fixture

    db, service = assignment_fixture.__wrapped__(db)
    saved = prepare(service)
    before = business(db)
    with client_for(db) as client:
        assert execute(client, saved).status_code == 409
        assert business(db) == before
        assert current(db, saved)["status"] == "WAITING_APPROVAL"
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved).status_code == 200
    assert current(db, saved)["status"] == "COMPLETED"
