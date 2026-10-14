"""UC-21: original input through approval, execution, projection and read."""

import io
import json
from uuid import uuid4

import pytest
from agent.test_read_agent import call
from application.test_dependency_prepare import create, uid
from application.test_dependency_prepare import service as dependency_fixture
from application.test_production_prepare import END, NEW_END, START
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver

from interfaces.test_controlled_action_scenarios import approve_execute, headers
from interfaces.test_dependency_action_api import client_for
from interfaces.test_graph_business_scenarios import inquire
from interfaces.test_production_assignment_flow import count
from linescope.agent.agent_input import AgentInput
from linescope.agent.update_intent import dependency_command
from linescope.execution import ExecutionContext
from linescope.graph.administration import GraphAdministration
from linescope.graph.graph_leadership import graph_leadership
from linescope.graph.projection_state import ProjectionState
from linescope.graph.projection_worker import ProjectionWorker
from linescope.logging import EventLogger


def create_message(**changes):
    values = {key: value for key, value in create(**changes).items() if key != "operation_type"}
    return "依存関係を" + json.dumps(values) + "で登録して"


def update_message(patch=None):
    return (
        f"依存関係{uid(200)}をパッチ"
        + json.dumps(patch or {"effective_to": NEW_END})
        + "で更新して"
    )


DISABLE = f"依存関係{uid(201)}を無効化して"


@pytest.fixture
def world(db):
    return dependency_fixture.__wrapped__(db)[0]


def post(client, message, token="requester"):
    return client.post("/agent", json={"message": message}, headers=headers(token))


@pytest.mark.parametrize("operation", ["CREATE", "UPDATE", "DISABLE"])
def test_dependency_input_to_projection_and_api_read(world, adapters, operation):
    driver = adapters[1].driver
    GraphAdministration(world, driver, logger=EventLogger(stream=io.StringIO())).rebuild()
    messages = {"CREATE": create_message(), "UPDATE": update_message(), "DISABLE": DISABLE}
    with client_for(world) as client:
        response = post(client, messages[operation])
        assert response.status_code == 200
        saved = response.json()["data"]
        target = saved["canonical_snapshot"]["targets"][0]
        assert target["operation_type"] == operation
        assert count(world, "graph_outbox") == count(world, "business_update_history") == 0
        endpoint = f"/update-requests/{saved['update_request_id']}/execute"
        assert client.post(endpoint, headers=headers()).status_code == 409
        confirmed = approve_execute(client, saved)
        assert confirmed["execution_result"]["targets"] == saved["canonical_snapshot"]["targets"]
        assert confirmed["current_snapshot"]["targets"][0]["snapshot"] == target["after"]
        assert count(world, "graph_outbox") == count(world, "business_update_history") == 1
        assert client.post(endpoint, headers=headers()).status_code == 200
        assert count(world, "graph_outbox") == count(world, "business_update_history") == 1
    assert ProjectionState(world).observe().status == "LAGGING"
    with graph_leadership(world) as leader:
        worker = ProjectionWorker(world, adapters[0], logger=EventLogger(stream=io.StringIO()))
        assert worker.run_once(leader).status == "APPLIED"
        assert worker.run_once(leader).status == "IDLE"
    assert ProjectionState(world).observe().status == "CURRENT"
    observed = inquire(
        world,
        driver,
        [call("get_dependency_relation", {"dependency_relation_id": target["target_id"]})],
        "保存した依存関係を調べて",
    )
    assert observed.status_code == 200
    current = observed.json()["data"]["tool_results"][0]["data"]
    assert current["dependency_relation_id"] == target["target_id"]
    assert current["version"] == target["after"]["version"]
    assert current["active"] == target["after"]["active"]
    source = target["after"]
    as_of = END if operation == "UPDATE" else START
    graph = inquire(
        world,
        driver,
        [
            call(
                "trace_upstream_dependencies",
                {
                    "target": {
                        "entity_type": source["source_entity_type"],
                        "entity_id": source["source_entity_id"],
                    },
                    "explicit_as_of": as_of,
                },
            )
        ],
        f"{as_of}の登録依存関係を調べて",
    )
    assert graph.status_code == 200
    data = graph.json()["data"]["tool_results"][0]["data"]
    assert data["complete"] and data["graph_sync_state"] == "CURRENT"
    referenced = {
        edge["source_record_id"] for path in data["representative_paths"] for edge in path["edges"]
    }
    assert (target["target_id"] in referenced) == (operation != "DISABLE")


def test_forbidden_cycle_creates_no_request(world):
    with client_for(world) as client:
        response = post(
            client,
            create_message(
                source_entity_type="Process",
                source_entity_id=uid(10),
                target_entity_type="Equipment",
                target_entity_id=uid(100),
            ),
        )
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
    assert count(world, "update_request") == 0


@pytest.mark.parametrize(
    "text",
    [
        '依存関係を{"required":true,"required":false}で登録して',
        '依存関係を{"operation_type":"DISABLE"}で登録して',
    ],
)
def test_ambiguous_json_and_operation_override_are_rejected(world, text):
    with client_for(world) as client:
        response = post(client, text)
        assert response.status_code == 400
        assert response.json()["errors"][0]["code"] == "INVALID_ARGUMENT"
    assert count(world, "update_request") == 0


def test_inactive_endpoint_is_not_accepted(world):
    with client_for(world) as client:
        response = post(
            client,
            create_message(
                source_entity_type="Equipment",
                source_entity_id=uid(102),
                target_entity_type="Process",
                target_entity_id=uid(11),
            ),
        )
        assert response.status_code == 422
    assert count(world, "update_request") == 0


def test_floor_cannot_prepare_dependency_change(world):
    with client_for(world) as client:
        assert post(client, create_message(), "floor").status_code == 403
    assert count(world, "update_request") == 0


def test_retry_keeps_create_id_and_rejects_changed_values(world):
    retry_headers = {**headers(), "Idempotency-Key": str(uuid4())}
    with client_for(world) as client:
        first = client.post("/agent", json={"message": create_message()}, headers=retry_headers)
        second = client.post("/agent", json={"message": create_message()}, headers=retry_headers)
        assert first.status_code == second.status_code == 200
        assert (
            first.json()["data"]["canonical_snapshot"]
            == second.json()["data"]["canonical_snapshot"]
        )
        changed = client.post(
            "/agent", json={"message": create_message(required=False)}, headers=retry_headers
        )
        assert changed.status_code == 409
        assert changed.json()["errors"][0]["code"] == "DUPLICATE_REQUEST"
    assert count(world, "update_request") == 1


def test_unknown_dependency_is_not_inferred(world):
    with client_for(world) as client:
        response = post(client, f"依存関係{uid(999)}を無効化して")
        assert response.status_code == 404
    assert count(world, "update_request") == 0


@pytest.mark.parametrize("text", [f"「{DISABLE}」", f"{DISABLE}？"])
def test_quoted_command_and_question_are_not_update_authority(text):
    request = AgentInput.parse(
        ExecutionContext("maintenance1", "maintenance", uuid4()),
        json.dumps({"message": text}),
        received_at="2026-10-14T00:00:00Z",
    )
    assert dependency_command(request) is None
