"""HTTP execution of saved plan UPDATEs with durable results and separate observation."""

import io
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_maintenance_plan_approval_api import act, client_for, current, headers
from test_maintenance_plan_approval_api import world as plan_world
from test_maintenance_prepare import prepare

from linescope.api import create_app
from linescope.execute import MaintenancePlanUpdateExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError
from linescope.settings import Settings


@pytest.fixture
def world(db):
    return plan_world.__wrapped__(db)


def execute(client, saved, token="requester", **kwargs):
    return client.post(
        f"/update-requests/{saved.update_request_id}/execute",
        headers=headers(token) if token else {},
        **kwargs,
    )


def plans(db):
    with db.transaction() as connection:
        return connection.execute(
            "SELECT plan_status,version FROM maintenance_plan ORDER BY maintenance_plan_id"
        ).fetchall()


def test_execute_all_plans_replay_and_get_separate_confirmed_and_current(world):
    db, _, saved = world
    with client_for(db) as client:
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
        assert len(data["current_versions"]) == 2
        assert all(item["version_delta"] == 0 for item in data["current_versions"])
        assert data["observed_at"]
        assert plans(db) == [{"plan_status": "CANCELLED", "version": 6}] * 2
        with db.transaction() as connection:
            history = connection.execute("SELECT * FROM business_update_history").fetchone()
            assert history["category"] == "MAINTENANCE"
            assert str(history["history_id"]) == data["execution_result"]["history_id"]
            assert (
                connection.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()[
                    "n"
                ]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT state_code FROM equipment_current_state ORDER BY equipment_id"
                ).fetchall()
                == [{"state_code": "RUNNING"}] * 2
            )
            connection.execute(
                "UPDATE maintenance_plan SET plan_status='PLANNED',version=7 WHERE maintenance_plan_id=%s",
                (UUID(int=20),),
            )
        replay = execute(client, saved)
        assert replay.status_code == 200
        replay_data = replay.json()["data"]
        assert replay_data["execution_result"] == data["execution_result"]
        assert [item["version_delta"] for item in replay_data["current_versions"]] == [1, 0]
        assert replay_data["current_snapshot"]["targets"][0]["snapshot"]["plan_status"] == "PLANNED"
        assert replay_data["execution_result"]["targets"][0]["after"]["plan_status"] == "CANCELLED"
        inspected = client.get(
            f"/update-requests/{saved.update_request_id}", headers=headers("requester")
        ).json()["data"]
        assert inspected["execution_result"] == data["execution_result"]
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='EXECUTE'"
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("token,status", [(None, 401), ("approver", 403), ("manager", 403)])
def test_only_original_requester_can_execute(world, token, status):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        result = execute(client, saved, token)
        assert result.status_code == status
        assert result.json()["data"] == {}
    assert current(db, saved)["status"] == "APPROVED"
    assert plans(db) == [{"plan_status": "PLANNED", "version": 5}] * 2


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", b'{"plan_status":"CANCELLED"}'])
def test_execute_requires_empty_body(world, body):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, content=body).status_code == 400
    assert current(db, saved)["status"] == "APPROVED"


@pytest.mark.parametrize("state", ["pending", "rejected", "expired"])
def test_unapproved_rejected_and_expired_requests_do_not_update_plans(world, state):
    db, _, saved = world
    with client_for(db) as client:
        if state == "rejected":
            assert act(client, saved, "reject").status_code == 200
        elif state == "expired":
            assert act(client, saved, "approve").status_code == 200
            with db.transaction() as connection:
                connection.execute(
                    "WITH t AS (SELECT clock_timestamp()-INTERVAL '31 minutes' AS at) "
                    "UPDATE approval SET approved_at=t.at,expires_at=t.at+INTERVAL '30 minutes' FROM t"
                )
        result = execute(client, saved)
        assert result.status_code == (410 if state == "expired" else 409)
        assert result.json()["errors"][0]["code"] == (
            "APPROVAL_EXPIRED" if state == "expired" else "INVALID_UPDATE_STATE"
        )
    assert plans(db) == [{"plan_status": "PLANNED", "version": 5}] * 2
    assert (
        current(db, saved)["status"]
        == {"pending": "WAITING_APPROVAL", "rejected": "REJECTED", "expired": "EXPIRED"}[state]
    )


def test_one_conflicting_plan_invalidates_all_without_partial_update(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as connection:
            connection.execute(
                "UPDATE maintenance_plan SET version=6 WHERE maintenance_plan_id=%s",
                (UUID(int=21),),
            )
        result = execute(client, saved)
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert plans(db) == [
        {"plan_status": "PLANNED", "version": 5},
        {"plan_status": "PLANNED", "version": 6},
    ]


@pytest.mark.parametrize("unexpected", [False, True])
def test_current_read_failure_returns_partial_without_changing_completed(
    world, monkeypatch, unexpected
):
    db, _, saved = world

    def fail(self, result):
        if unexpected:
            raise RuntimeError("private-secret")
        raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-secret")

    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        monkeypatch.setattr(MaintenancePlanUpdateExecute, "observe_current", fail)
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


def test_execute_audit_failure_rolls_back_everything_then_retry_succeeds(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as connection:
            connection.execute("""CREATE FUNCTION fail_execute_audit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.action='EXECUTE' THEN RAISE EXCEPTION 'private-secret'; END IF;
                RETURN NEW; END $$""")
            connection.execute(
                "CREATE TRIGGER fail_execute_audit BEFORE INSERT ON update_audit_event "
                "FOR EACH ROW EXECUTE FUNCTION fail_execute_audit()"
            )
        result = execute(client, saved)
        assert result.status_code == 500 and "private-secret" not in result.text
        assert current(db, saved)["status"] == "APPROVED"
        assert plans(db) == [{"plan_status": "PLANNED", "version": 5}] * 2
        with db.transaction() as connection:
            assert (
                connection.execute("SELECT count(*) AS n FROM business_update_history").fetchone()[
                    "n"
                ]
                == 0
            )
            connection.execute("DROP TRIGGER fail_execute_audit ON update_audit_event")
        assert execute(client, saved).status_code == 200


@pytest.mark.parametrize("lost", ["requester", "approver"])
@pytest.mark.parametrize("completed", [False, True])
def test_current_permission_loss_invalidates_new_execution_but_not_completed_replay(
    world, lost, completed
):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        confirmed = execute(client, saved).json()["data"]["execution_result"] if completed else None
    settings = Settings(
        users={
            "requester": {
                "user_id": "maintenance1",
                "role": "floor" if lost == "requester" else "maintenance",
            },
            "approver": {
                "user_id": "approver",
                "role": "floor" if lost == "approver" else "maintenance",
            },
        }
    )
    with TestClient(create_app(settings, db, EventLogger(stream=io.StringIO()))) as client:
        result = execute(client, saved)
        if completed:
            assert result.status_code == 200
            assert result.json()["data"]["execution_result"] == confirmed
        else:
            assert result.status_code == 409
            assert result.json()["errors"][0]["code"] == "APPROVAL_INVALIDATED"
    assert current(db, saved)["status"] == ("COMPLETED" if completed else "INVALIDATED")
    assert (
        plans(db)
        == [
            {
                "plan_status": "CANCELLED" if completed else "PLANNED",
                "version": 6 if completed else 5,
            }
        ]
        * 2
    )


def test_parallel_http_execution_has_one_durable_result(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.map(lambda _: execute(client, saved), range(2))
        assert first.status_code == second.status_code == 200
        assert first.json()["data"]["execution_result"] == second.json()["data"]["execution_result"]
    assert plans(db) == [{"plan_status": "CANCELLED", "version": 6}] * 2
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"]
            == 1
        )


def test_pending_composite_request_cannot_execute(world):
    db, service, _ = world
    saved = prepare(service)
    with client_for(db) as client:
        result = execute(client, saved)
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == "INVALID_UPDATE_STATE"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
