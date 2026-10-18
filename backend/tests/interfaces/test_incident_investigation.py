from uuid import uuid4

import pytest
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from incident_graph_fixture import seed_incident_demo
from incident_loss_fixture import END, START, records

from interfaces.test_registered_decisions import auth, client
from linescope.demo_seed import DEMO_EQUIPMENT
from linescope.graph.administration import GraphAdministration


@pytest.fixture
def incident(db, adapters):
    db.migrate()
    seed_incident_demo(db)
    GraphAdministration(db, adapters[1].driver).rebuild()
    return {
        "equipment_ids": [str(row[0]) for row in DEMO_EQUIPMENT],
        "economic_input_ids": [
            target["target_id"]
            for queries, target in records()
            if queries.INPUT.name == "economic_input"
        ],
        "period_start": START,
        "period_end": END,
    }


@pytest.mark.parametrize("role", ["manager", "floor"])
def test_incident_read_role_boundary(db, adapters, incident, role):
    with client(db, adapters[1].driver) as api:
        result = api.post("/incidents/investigate", json=incident, headers=auth(role))
    assert result.status_code == (403 if role == "floor" else 200)


def test_incident_real_graph_total_and_running_state_requery_without_writes(db, adapters, incident):
    with client(db, adapters[1].driver) as api:
        result = api.post("/incidents/investigate", json=incident, headers=auth())
        assert result.status_code == 200, result.text
        data = result.json()["data"]
        assert data["loss"]["loss_per_hour"] == "250000"
        assert len(data["loss"]["items"]) == 3
        assert len(data["evidence"]["registered_inputs"]) == 2
        assert all(row["impact"]["representative_paths"] for row in data["impacts"])
        # A state-only change is read from PG; Graph reachability is not restoration.
        with db.transaction() as connection:
            connection.execute(
                "UPDATE equipment_current_state SET state_code='RUNNING',version=version+1 WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[1][0],),
            )
        again = api.post("/incidents/investigate", json=incident, headers=auth()).json()["data"]
        assert again["loss"]["loss_per_hour"] == "200000"
        assert again["impacts"][1]["state_code"] == "RUNNING"
        bad = {**incident, "role": "manager"}
        assert api.post("/incidents/investigate", json=bad, headers=auth()).status_code == 400
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize("change", ["period", "missing", "noncurrent"])
def test_incident_period_missing_inputs_and_noncurrent_are_not_zero_damage(
    db, adapters, incident, change
):
    if change == "period":
        incident["period_start"] = "2026-10-17T00:00:00Z"
    elif change == "missing":
        incident["economic_input_ids"] = []
    else:
        with db.transaction() as connection:
            connection.execute(
                "UPDATE graph_projection_control SET fatal_error='injected_test_error'"
            )
    with client(db, adapters[1].driver) as api:
        result = api.post("/incidents/investigate", json=incident, headers=auth())
    if change == "noncurrent":
        assert result.status_code == 503 and result.json()["errors"]
    else:
        assert result.status_code == 200
        assert result.json()["status"] == "partial"
        assert result.json()["data"]["loss"]["loss_per_hour"] is None


def test_incident_economic_scope_is_saved_approved_and_executed_with_snapshot_hash(
    db, adapters, incident
):
    from fastapi.testclient import TestClient

    from linescope.interfaces.api import create_app
    from linescope.settings import Settings

    record = next(
        target["after"] for queries, target in records() if queries.INPUT.name == "economic_input"
    )
    payload = record["payload"]
    payload["incident_losses"][1]["loss_per_hour"] = "90000"
    settings = Settings(
        users={
            "requester": {"user_id": "requester", "role": "manager"},
            "approver": {"user_id": "approver", "role": "manager"},
        }
    )
    with TestClient(create_app(settings, db, graph_driver=adapters[1].driver)) as api:
        prepared = api.post(
            "/economic-inputs/prepare",
            headers=auth("requester"),
            json={
                "retry_key": str(uuid4()),
                "economic_input_id": record["economic_input_id"],
                "input": {
                    "input_code": record["input_code"],
                    "equipment_id": record["equipment_id"],
                    "payload": payload,
                },
                "supersedes_update_request_id": None,
            },
        )
        assert prepared.status_code == 200, prepared.text
        saved = prepared.json()["data"]
        assert saved["snapshot_schema_version"] == 7
        approved = api.post(
            f"/approvals/{saved['approval_id']}/approve",
            headers=auth("approver"),
            json={"snapshot_hash": saved["snapshot_hash"]},
        )
        assert approved.status_code == 200, approved.text
        executed = api.post(
            f"/update-requests/{saved['update_request_id']}/execute", headers=auth("requester")
        )
        assert executed.status_code == 200, executed.text
        refreshed = api.post("/incidents/investigate", json=incident, headers=auth("requester"))
        assert refreshed.json()["data"]["loss"]["loss_per_hour"] == "260000"
