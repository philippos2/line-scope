"""Human dependency actions preserve Graph lock ordering and durable results."""

import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_dependency_approval import business, current
from test_dependency_prepare import create, disable, prepare, update
from test_dependency_prepare import service as dependency_fixture
from test_maintenance_plan_approval_api import act, headers
from test_maintenance_record_create_api import execute

from linescope.api import create_app
from linescope.database import Database
from linescope.dependency_execute import DependencyExecute
from linescope.graph_locks import acquire_graph_mutation_lock
from linescope.logging import EventLogger
from linescope.proposals import ProposalError
from linescope.settings import Settings


@pytest.fixture
def world(db):
    db, service = dependency_fixture.__wrapped__(db)
    return db, service, prepare(service, [create(), update(), disable()])


def client_for(db, requester_role="maintenance", approver_role="manager"):
    return TestClient(
        create_app(
            Settings(
                users={
                    "requester": {"user_id": "production1", "role": requester_role},
                    "approver": {"user_id": "approver", "role": approver_role},
                    "floor": {"user_id": "floor", "role": "floor"},
                    "production": {"user_id": "production", "role": "production"},
                    "maintenance": {"user_id": "maintenance", "role": "maintenance"},
                }
            ),
            db,
            EventLogger(stream=io.StringIO()),
        )
    )


@pytest.mark.parametrize(
    "operations", [[create()], [update()], [disable()], [create(), update(), disable()]]
)
def test_inspection_actions_current_values_and_durable_replay(db, operations):
    db, service = dependency_fixture.__wrapped__(db)
    saved = prepare(service, operations)
    with client_for(db) as client:
        viewed = client.get(
            f"/update-requests/{saved.update_request_id}", headers=headers("requester")
        )
        assert viewed.status_code == 200
        assert viewed.json()["data"]["canonical_snapshot"] == saved.snapshot.data
        assert act(client, saved, "approve").status_code == 200
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "ok"
        data = response.json()["data"]
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["execution_result"]["targets"] == saved.snapshot.data["targets"]
        assert [t["snapshot"] for t in data["current_snapshot"]["targets"]] == [
            t["after"] for t in saved.snapshot.data["targets"]
        ]
        assert data["observed_at"] and all(
            v["version_delta"] == 0 for v in data["current_versions"]
        )
        changed = saved.snapshot.data["targets"][0]["target_id"]
        with db.transaction() as c:
            c.execute(
                "UPDATE dependency_relation SET required=NOT required,version=version+1 WHERE dependency_relation_id=%s",
                (changed,),
            )
        replay = execute(client, saved).json()["data"]
        assert replay["execution_result"] == data["execution_result"]
        assert replay["current_versions"][0]["version_delta"] == 1
        assert (
            replay["current_snapshot"]["targets"][0]["snapshot"]["required"]
            != data["execution_result"]["targets"][0]["after"]["required"]
        )
        with db.transaction() as c:
            assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == len(
                operations
            )
            assert (
                c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1
            )


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(
    "token,status",
    [
        (None, 401),
        ("floor", 403),
        ("production", 403),
        ("maintenance", 403),
        ("requester", 403),
        ("owner-manager", 403),
    ],
)
def test_approval_requires_other_manager(world, action, token, status):
    db, _, saved = world
    with client_for(
        db, requester_role="manager" if token == "owner-manager" else "maintenance"
    ) as client:
        assert (
            act(
                client, saved, action, "requester" if token == "owner-manager" else token
            ).status_code
            == status
        )
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("token,status", [(None, 401), ("approver", 403), ("production", 403)])
def test_execute_requires_original_requester(world, token, status):
    db, _, saved = world
    before = business(db)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, token).status_code == status
    assert current(db, saved)["status"] == "APPROVED" and business(db) == before


def test_wrong_hash_body_injection_and_rejection(world):
    db, _, saved = world
    with client_for(db) as client:
        bad = act(client, saved, "approve", snapshot_hash="0" * 64)
        assert (
            bad.status_code == 409 and bad.json()["errors"][0]["code"] == "APPROVAL_HASH_MISMATCH"
        )
        assert current(db, saved)["status"] == "WAITING_APPROVAL"
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, json={"required": False}).status_code == 400
        assert act(client, saved, "reject").status_code == 409
    assert current(db, saved)["status"] == "APPROVED"


def test_pending_rejection_prevents_execute(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "reject").status_code == 200
        assert execute(client, saved).status_code == 409
    assert current(db, saved)["status"] == "REJECTED"


@pytest.mark.parametrize("phase", ["approve", "execute"])
def test_changed_target_is_409_and_invalidates_all(world, phase):
    db, _, saved = world
    with client_for(db) as client:
        if phase == "execute":
            assert act(client, saved, "approve").status_code == 200
        with db.transaction() as c:
            c.execute(
                "UPDATE dependency_relation SET version=6 WHERE dependency_relation_id=%s",
                (UUID(int=201),),
            )
        before = business(db)
        response = act(client, saved, "approve") if phase == "approve" else execute(client, saved)
        assert (
            response.status_code == 409
            and response.json()["errors"][0]["code"] == "VERSION_CONFLICT"
        )
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before


def test_inactive_endpoint_returns_422_without_partial_update(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as c:
            c.execute("UPDATE infrastructure_resource SET active=false")
        before = business(db)
        response = execute(client, saved)
        assert (
            response.status_code == 422
            and response.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
        )
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before


@pytest.mark.parametrize("lost", ["requester", "approver"])
def test_current_permission_loss_invalidates_approval(world, lost):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
    with client_for(
        db,
        requester_role="floor" if lost == "requester" else "maintenance",
        approver_role="production" if lost == "approver" else "manager",
    ) as client:
        response = execute(client, saved)
        assert (
            response.status_code == 409
            and response.json()["errors"][0]["code"] == "APPROVAL_INVALIDATED"
        )
    assert current(db, saved)["status"] == "INVALIDATED"


def test_expired_approval_returns_410(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as c:
            c.execute(
                "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',expires_at=statement_timestamp()-interval '1 minute'"
            )
        response = execute(client, saved)
        assert (
            response.status_code == 410
            and response.json()["errors"][0]["code"] == "APPROVAL_EXPIRED"
        )
    assert current(db, saved)["status"] == "EXPIRED"


@pytest.mark.parametrize("shared", [True, False])
def test_http_graph_lock_timeout_is_503_and_retryable(world, shared):
    db, _, saved = world
    short = Database(replace(db.settings, lock_ms=50))
    with client_for(short) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as holder:
            acquire_graph_mutation_lock(holder, shared=shared)
            response = execute(client, saved)
        assert (
            response.status_code == 503 and response.json()["errors"][0]["code"] == "RESOURCE_BUSY"
        )
        assert current(db, saved)["status"] == "APPROVED"
        assert execute(client, saved).status_code == 200
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 3


@pytest.mark.parametrize("unexpected", [False, True])
def test_observation_failure_keeps_completed_result(world, monkeypatch, unexpected):
    db, _, saved = world

    def fail(self, result):
        if unexpected:
            raise RuntimeError("private-secret")
        raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-secret")

    monkeypatch.setattr(DependencyExecute, "observe_current", fail)
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


def test_deleted_current_target_keeps_completed_result(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        confirmed = execute(client, saved).json()["data"]["execution_result"]
        with db.transaction() as c:
            c.execute(
                "DELETE FROM dependency_relation WHERE dependency_relation_id=%s", (UUID(int=201),)
            )
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        assert response.json()["warnings"][0]["code"] == "TARGET_NOT_FOUND"
        assert response.json()["data"]["execution_result"] == confirmed


def test_parallel_http_execute_has_one_durable_result(world):
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
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 3
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1


def test_schedule_only_api_is_not_blocked_by_graph_analysis_lock(db):
    from test_production_schedule_api import client_for as schedule_client
    from test_production_schedule_approval import world as schedule_fixture

    db, _, saved = schedule_fixture.__wrapped__(db)
    short = Database(replace(db.settings, lock_ms=50))
    with schedule_client(short) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as holder:
            acquire_graph_mutation_lock(holder, shared=True)
            assert execute(client, saved).status_code == 200
