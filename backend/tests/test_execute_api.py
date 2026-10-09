import pytest
from test_approval_api import client_for, headers, prepare
from test_approval_api import world as seeded_world

from linescope.demo_seed import DEMO_EQUIPMENT
from linescope.execute import EquipmentExecute
from linescope.proposals import ProposalError


@pytest.fixture
def world(db):
    return seeded_world.__wrapped__(db)


def approved(client):
    saved = prepare(client)
    assert (
        client.post(
            f"/approvals/{saved['approval_id']}/approve",
            json={"snapshot_hash": saved["snapshot_hash"]},
            headers=headers(),
        ).status_code
        == 200
    )
    return saved


def execute(client, saved, **kwargs):
    return client.post(
        f"/update-requests/{saved['update_request_id']}/execute",
        headers=headers("requester"),
        **kwargs,
    )


def test_end_to_end_execution_get_and_replay_show_confirmed_and_current(world):
    with client_for(world) as client:
        saved = approved(client)
        first = execute(client, saved)
        assert first.status_code == 200
        data = first.json()["data"]
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["current_versions"][0]["version_delta"] == 0
        assert data["observed_at"]
        with world.transaction() as c:
            c.execute(
                "UPDATE equipment_current_state SET state_code='UNKNOWN',version=3 WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            )
        replay = execute(client, saved).json()["data"]
        assert replay["execution_result"] == data["execution_result"]
        assert replay["current_versions"][0]["version_delta"] == 1
        assert replay["current_snapshot"]["targets"][0]["snapshot"]["state_code"] == "UNKNOWN"
        assert replay["execution_result"]["targets"][0]["after"]["state_code"] == "RUNNING"
        observed = client.get(
            f"/update-requests/{saved['update_request_id']}", headers=headers("requester")
        )
        assert observed.json()["data"]["execution_result"] == data["execution_result"]


@pytest.mark.parametrize("token,expected", [(None, 401), ("approver", 403), ("manager", 403)])
def test_nonowner_cannot_execute(world, token, expected):
    with client_for(world) as client:
        saved = approved(client)
        result = client.post(
            f"/update-requests/{saved['update_request_id']}/execute",
            headers=headers(token) if token else {},
        )
        assert result.status_code == expected
        assert result.json()["data"] == {}


@pytest.mark.parametrize("body", [b"{}", b"null", b" ", b'{"state_code":"RUNNING"}'])
def test_execute_requires_empty_body(world, body):
    with client_for(world) as client:
        saved = approved(client)
        assert execute(client, saved, content=body).status_code == 400


def test_pending_and_expired_requests_are_rejected(world):
    with client_for(world) as client:
        pending = prepare(client)
        assert execute(client, pending).status_code == 409
        client.post(
            f"/approvals/{pending['approval_id']}/approve",
            json={"snapshot_hash": pending["snapshot_hash"]},
            headers=headers(),
        )
        with world.transaction() as c:
            c.execute(
                "WITH t AS (SELECT clock_timestamp()-INTERVAL '31 minutes' AS at) UPDATE approval SET approved_at=t.at,expires_at=t.at+INTERVAL '30 minutes' FROM t"
            )
        expired = execute(client, pending)
        assert (
            expired.status_code == 410 and expired.json()["errors"][0]["code"] == "APPROVAL_EXPIRED"
        )


@pytest.mark.parametrize("unexpected", [False, True])
def test_current_read_failure_keeps_completed_result_and_returns_partial(
    world, monkeypatch, unexpected
):
    with client_for(world) as client:
        saved = approved(client)

        def fail(self, result):
            if unexpected:
                raise RuntimeError("private-secret")
            raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-secret")

        monkeypatch.setattr(EquipmentExecute, "observe_current", fail)
        result = execute(client, saved)
        body = result.json()
        assert result.status_code == 200 and body["status"] == "partial"
        assert body["data"]["status"] == "COMPLETED"
        assert body["data"]["execution_result"]["history_id"]
        assert body["data"]["current_snapshot"] is body["data"]["observed_at"] is None
        assert body["warnings"][0]["code"] == (
            "INTERNAL_ERROR" if unexpected else "DEPENDENCY_UNAVAILABLE"
        )
        assert "private-secret" not in result.text
        assert (
            client.get(
                f"/update-requests/{saved['update_request_id']}", headers=headers("requester")
            ).json()["data"]["status"]
            == "COMPLETED"
        )
