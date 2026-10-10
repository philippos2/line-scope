"""Mixed maintenance HTTP execution and one-statement current observation."""

import io
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_maintenance_composite_execute import approved, business
from test_maintenance_plan_approval_api import client_for, current
from test_maintenance_prepare import create_plan, create_record, prepare, update
from test_maintenance_prepare import service as maintenance_fixture
from test_maintenance_record_create_api import execute

from linescope.api import create_app
from linescope.execute import MaintenanceExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError
from linescope.settings import Settings


@pytest.fixture
def world(db):
    db, service = maintenance_fixture.__wrapped__(db)
    return db, service


@pytest.mark.parametrize("kind", ["all", "update_record", "create_record", "update_create"])
def test_mixed_http_execution_and_replay_separate_confirmed_current(world, kind):
    db, service = world
    targets = {
        "all": None,
        "update_record": [update(), create_record()],
        "create_record": [create_plan(), create_record(plan_id=None)],
        "update_create": [update(), create_plan()],
    }[kind]
    saved = approved(db, service, targets)
    with client_for(db) as client:
        first = execute(client, saved)
        assert first.status_code == 200
        body = first.json()
        assert body["status"] == "ok" and body["errors"] == body["warnings"] == []
        assert body["context_id"] is None
        data = body["data"]
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["execution_result"]["targets"] == saved.snapshot.data["targets"]
        assert data["observed_at"]
        for observed, target in zip(
            data["current_snapshot"]["targets"], saved.snapshot.data["targets"], strict=True
        ):
            assert observed["target_type"] == target["target_type"]
            assert observed["target_id"] == target["target_id"]
            assert observed["snapshot"] == target["after"]
        assert all(item["version_delta"] == 0 for item in data["current_versions"])
        with db.transaction() as c:
            for target in saved.snapshot.data["targets"]:
                if target["target_type"] == "MaintenanceRecord":
                    c.execute(
                        "UPDATE maintenance_record SET result='Later observation',version=version+1 WHERE maintenance_record_id=%s",
                        (target["target_id"],),
                    )
                else:
                    c.execute(
                        "UPDATE maintenance_plan SET planned_end=planned_end+interval '1 hour',version=version+1 WHERE maintenance_plan_id=%s",
                        (target["target_id"],),
                    )
        replay = execute(client, saved).json()["data"]
        assert replay["execution_result"] == data["execution_result"]
        assert all(
            item["version_delta"] == 1 and item["version"] == item["confirmed_version"] + 1
            for item in replay["current_versions"]
        )
        assert replay["current_snapshot"] != data["current_snapshot"]
    assert business(db)["histories"] == 1


@pytest.mark.parametrize("fault", ["dependency", "unexpected"])
def test_current_failure_preserves_completed_result(world, monkeypatch, fault):
    db, service = world
    saved = approved(db, service)

    def fail(self, result):
        if fault == "dependency":
            raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-secret")
        raise RuntimeError("private-secret")

    monkeypatch.setattr(MaintenanceExecute, "observe_current", fail)
    with client_for(db) as client:
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        body = response.json()
        data = body["data"]
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["current_snapshot"] is data["current_versions"] is data["observed_at"] is None
        assert body["warnings"][0]["code"] == (
            "DEPENDENCY_UNAVAILABLE" if fault == "dependency" else "INTERNAL_ERROR"
        )
        assert body["errors"] == [] and "private-secret" not in response.text
        assert execute(client, saved).json()["data"]["execution_result"] == data["execution_result"]
    assert current(db, saved)["status"] == "COMPLETED"


@pytest.mark.parametrize("target_type", ["MaintenancePlan", "MaintenanceRecord"])
def test_one_deleted_current_target_makes_whole_observation_partial(world, target_type):
    db, service = world
    saved = approved(db, service)
    with client_for(db) as client:
        confirmed = execute(client, saved).json()["data"]["execution_result"]
        target = next(
            t
            for t in saved.snapshot.data["targets"]
            if t["target_type"] == target_type and t["operation_type"] == "CREATE"
        )
        with db.transaction() as c:
            query = (
                "DELETE FROM maintenance_plan WHERE maintenance_plan_id=%s"
                if target_type == "MaintenancePlan"
                else "DELETE FROM maintenance_record WHERE maintenance_record_id=%s"
            )
            c.execute(query, (target["target_id"],))
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        assert response.json()["warnings"][0]["code"] == "TARGET_NOT_FOUND"
        assert response.json()["data"]["execution_result"] == confirmed
        assert response.json()["data"]["current_snapshot"] is None
    assert current(db, saved)["status"] == "COMPLETED"


@pytest.mark.parametrize("token,status", [(None, 401), ("approver", 403), ("manager", 403)])
def test_only_original_authenticated_requester_can_execute_mixed(world, token, status):
    db, service = world
    saved = approved(db, service)
    before = business(db)
    with client_for(db) as client:
        assert execute(client, saved, token).status_code == status
    assert business(db) == before and current(db, saved)["status"] == "APPROVED"


def test_write_failure_is_500_and_all_targets_rollback_before_retry(world):
    db, service = world
    saved = approved(db, service)
    before = business(db)
    with db.transaction() as c:
        c.execute(
            """CREATE FUNCTION fail_mixed_http() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-secret'; END $$"""
        )
        c.execute(
            "CREATE TRIGGER fail_mixed_http BEFORE INSERT ON maintenance_record FOR EACH ROW EXECUTE FUNCTION fail_mixed_http()"
        )
    with client_for(db) as client:
        response = execute(client, saved)
        assert response.status_code == 500 and "private-secret" not in response.text
        assert response.json()["errors"][0]["code"] == "INTERNAL_ERROR"
        assert current(db, saved)["status"] == "APPROVED" and business(db) == before
        with db.transaction() as c:
            c.execute("DROP TRIGGER fail_mixed_http ON maintenance_record")
        assert execute(client, saved).status_code == 200


def test_reference_failure_is_422_without_partial_plan_creation(world):
    db, service = world
    saved = approved(db, service, [create_plan(), create_record()])
    with db.transaction() as c:
        c.execute(
            "UPDATE maintenance_plan SET equipment_id=%s WHERE maintenance_plan_id=%s",
            (UUID(int=11), UUID(int=20)),
        )
    before = business(db)
    with client_for(db) as client:
        response = execute(client, saved)
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
    assert business(db) == before and current(db, saved)["status"] == "INVALIDATED"


def test_parallel_mixed_http_calls_replay_one_result(world):
    db, service = world
    saved = approved(db, service)
    with client_for(db) as client:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: execute(client, saved), range(2)))
        assert all(r.status_code == 200 for r in results)
        assert (
            results[0].json()["data"]["execution_result"]
            == results[1].json()["data"]["execution_result"]
        )
    assert business(db)["histories"] == 1


def test_completed_mixed_owner_replay_after_permission_loss(world):
    db, service = world
    saved = approved(db, service)
    with client_for(db) as client:
        confirmed = execute(client, saved).json()["data"]["execution_result"]
    settings = Settings(users={"requester": {"user_id": "maintenance1", "role": "floor"}})
    with TestClient(create_app(settings, db, EventLogger(stream=io.StringIO()))) as client:
        response = execute(client, saved)
        assert response.status_code == 200
        assert response.json()["data"]["execution_result"] == confirmed
    assert business(db)["histories"] == 1


def test_pending_mixed_request_and_injected_execution_values_are_rejected(world):
    db, service = world
    saved = prepare(service)
    with client_for(db) as client:
        response = execute(client, saved)
        assert response.status_code == 409
        assert response.json()["errors"][0]["code"] == "INVALID_UPDATE_STATE"
    saved = approved(db, service)
    before = business(db)
    with client_for(db) as client:
        assert execute(client, saved, json={"targets": []}).status_code == 400
    assert business(db) == before and current(db, saved)["status"] == "APPROVED"


@pytest.mark.parametrize("fault", ["version", "create"])
def test_target_conflicts_are_409_and_invalidate_whole_request(world, fault):
    db, service = world
    saved = approved(db, service)
    with db.transaction() as c:
        if fault == "version":
            c.execute(
                "UPDATE maintenance_plan SET version=6 WHERE maintenance_plan_id=%s",
                (UUID(int=20),),
            )
        else:
            after = next(
                t["after"]
                for t in saved.snapshot.data["targets"]
                if t["target_type"] == "MaintenanceRecord"
            )
            c.execute(
                "INSERT INTO maintenance_record(maintenance_record_id,record_code,equipment_id,performed_at,result) VALUES(%s,%s,%s,%s,%s)",
                (
                    UUID(int=100),
                    after["record_code"],
                    after["equipment_id"],
                    after["performed_at"],
                    after["result"],
                ),
            )
    before = business(db)
    with client_for(db) as client:
        response = execute(client, saved)
        assert response.status_code == 409
        assert response.json()["errors"][0]["code"] == (
            "VERSION_CONFLICT" if fault == "version" else "CREATE_CONFLICT"
        )
    assert business(db) == before and current(db, saved)["status"] == "INVALIDATED"


def test_mixed_approval_expiry_is_410_without_business_changes(world):
    db, service = world
    saved = approved(db, service)
    with db.transaction() as c:
        c.execute(
            "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',expires_at=statement_timestamp()-interval '1 minute' WHERE approval_id=%s",
            (saved.approval_id,),
        )
    before = business(db)
    with client_for(db) as client:
        response = execute(client, saved)
        assert response.status_code == 410
        assert response.json()["errors"][0]["code"] == "APPROVAL_EXPIRED"
    assert business(db) == before and current(db, saved)["status"] == "EXPIRED"
