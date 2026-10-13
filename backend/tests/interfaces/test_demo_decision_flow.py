"""Temporary M0 journey: real storage/approval, explicitly mocked comparison."""

from fastapi.testclient import TestClient
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world

from interfaces.test_controlled_action_scenarios import approve_execute, counts, headers
from linescope.interfaces.api import create_app
from linescope.settings import Settings


def demo_client(db, driver):
    return TestClient(
        create_app(
            Settings(
                demo_decision_mock=True,
                users={
                    "requester": {"user_id": "maint1", "role": "maintenance"},
                    "approver": {"user_id": "maint2", "role": "maintenance"},
                    "floor": {"user_id": "floor1", "role": "floor"},
                },
            ),
            db,
            graph_driver=driver,
        )
    )


def test_comparison_to_approved_execution_and_current_confirmation(db, reader_world, adapters):
    with demo_client(db, adapters[1].driver) as client:
        response = client.post(
            "/agent", json={"message": "M-204の修理と交換を比較して"}, headers=headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        package = body["data"]["decision_package"]
        assert package["equipment"]["state_code"] == "STOPPED"
        assert package["comparison"]["source"] == "MOCK_FIXTURE"
        assert package["comparison"]["options"][0]["total_cost"] == 1900000
        assert package["comparison"]["options"][2]["shortage_units_per_hour"] == 30
        assert body["evidence"]["state"] and body["evidence"]["impact"]
        assert counts(db)["business_update_history"] == 0
        prepared = client.post(
            "/agent",
            json={"message": package["next_actions"]["prepare_message"]},
            headers=headers(),
        )
        assert prepared.status_code == 200
        saved = prepared.json()["data"]
        assert saved["canonical_snapshot"]["targets"][0]["before"]["state_code"] == "STOPPED"
        endpoint = f"/update-requests/{saved['update_request_id']}/execute"
        assert client.post(endpoint, headers=headers()).status_code == 409
        approve_execute(client, saved)
        committed = counts(db)
        assert committed["business_update_history"] == 1
        assert client.post(endpoint, headers=headers()).status_code == 200
        assert counts(db) == committed
        current = client.post(
            "/agent", json={"message": "M-204の修理と交換を比較して"}, headers=headers()
        )
        assert current.status_code == 200
        assert (
            current.json()["data"]["decision_package"]["equipment"]["state_code"]
            == "UNDER_MAINTENANCE"
        )


def test_demo_comparison_does_not_grant_graph_permission(db, reader_world, adapters):
    with demo_client(db, adapters[1].driver) as client:
        response = client.post(
            "/agent", json={"message": "M-204を比較して"}, headers=headers("floor")
        )
        assert response.status_code == 403
        assert counts(db)["business_update_history"] == 0


def test_demo_mode_is_disabled_by_default():
    assert Settings().demo_decision_mock is False
