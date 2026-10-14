"""UC-09: explicit assignment input through execution, projection and API read."""

import io
import json
from uuid import UUID, uuid4

import pytest
from agent.test_read_agent import call
from application.test_production_assignment_prepare import END, START
from application.test_production_assignment_prepare import service as production_fixture
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from sqlalchemy import func, select, table

from interfaces.test_controlled_action_scenarios import approve_execute, headers, query
from interfaces.test_graph_business_scenarios import inquire
from interfaces.test_production_schedule_api import client_for
from linescope.agent.agent_input import AgentInput
from linescope.agent.update_intent import production_assignment_command
from linescope.execution import ExecutionContext
from linescope.graph.administration import GraphAdministration
from linescope.graph.graph_leadership import graph_leadership
from linescope.graph.projection_state import ProjectionState
from linescope.graph.projection_worker import ProjectionWorker
from linescope.logging import EventLogger
from linescope.persistence.core_reads import get_operation_by_code


def message(equipment="EQ101,EQ102", end=END):
    return f"生産作業OP20の設備割当を開始{START}、終了{end}、設備[{equipment}]に置換して"


@pytest.fixture
def world(db):
    return production_fixture.__wrapped__(db)[0]


def post(client, text, token="requester", **kwargs):
    return client.post("/agent", json={"message": text}, headers=headers(token), **kwargs)


def count(database, name):
    assert name in {"update_request", "graph_outbox", "business_update_history"}
    return query(database, select(func.count().label("n")).select_from(table(name)))[0]["n"]


def upstream(database, driver, as_of):
    return inquire(
        database,
        driver,
        [
            call(
                "trace_upstream_dependencies",
                {
                    "target": {
                        "entity_type": "ProductionOperation",
                        "entity_id": str(UUID(int=20)),
                    },
                    "explicit_as_of": as_of,
                },
            )
        ],
        f"{as_of}におけるOP20の依存設備を調べて",
    )


@pytest.mark.parametrize("equipment,end", [("EQ101,EQ102", END), ("", "無期限")])
def test_assignment_input_to_execution_projection_and_api_confirmation(
    world, adapters, equipment, end
):
    driver = adapters[1].driver
    GraphAdministration(world, driver, logger=EventLogger(stream=io.StringIO())).rebuild()
    with client_for(world) as client:
        response = post(client, message(equipment, end))
        assert response.status_code == 200
        saved = response.json()["data"]
        parent = next(
            target
            for target in saved["canonical_snapshot"]["targets"]
            if target["target_type"] == "ProductionOperation"
        )
        assert parent["expected_version"] == 7 and parent["after"]["version"] == 8
        assert len(parent["before"]["equipment_assignments"]) == 1
        assert count(world, "graph_outbox") == count(world, "business_update_history") == 0
        endpoint = f"/update-requests/{saved['update_request_id']}/execute"
        assert client.post(endpoint, headers=headers()).status_code == 409
        confirmed = approve_execute(client, saved)
        assert confirmed["execution_result"]["targets"] == saved["canonical_snapshot"]["targets"]
        emitted = count(world, "graph_outbox")
        assert emitted > 0 and count(world, "business_update_history") == 1
        assert client.post(endpoint, headers=headers()).status_code == 200
        assert count(world, "graph_outbox") == emitted
    assert ProjectionState(world).observe().status == "LAGGING"
    blocked = upstream(world, driver, START)
    assert blocked.status_code == 503
    assert blocked.json()["errors"][0]["code"] == "GRAPH_NOT_CURRENT"
    worker = ProjectionWorker(world, adapters[0], logger=EventLogger(stream=io.StringIO()))
    with graph_leadership(world) as leader:
        for _ in range(emitted):
            assert worker.run_once(leader).status == "APPLIED"
        assert worker.run_once(leader).status == "IDLE"
    assert ProjectionState(world).observe().status == "CURRENT"
    for as_of, expected in (
        (START, {101, 102} if equipment else set()),
        (END, {100} if equipment else set()),
    ):
        observed = upstream(world, driver, as_of)
        assert observed.status_code == 200
        data = observed.json()["data"]["tool_results"][0]["data"]
        assert data["complete"] and data["graph_sync_state"] == "CURRENT"
        assert {
            node["entity_id"]
            for node in data["reached_nodes"]
            if node["entity_type"] == "Equipment"
        } == {str(UUID(int=value)) for value in expected}
        read = inquire(
            world,
            driver,
            [
                call(
                    "get_operation_equipment_assignments",
                    {"production_operation_id": str(UUID(int=20)), "explicit_as_of": as_of},
                )
            ],
            f"{as_of}におけるOP20の割当を調べて",
        )
        assert read.status_code == 200
        assignments = read.json()["data"]["tool_results"][0]["data"]
        assert assignments["parent_version"] == 8
        assert {row["equipment_id"] for row in assignments["items"]} == {
            str(UUID(int=value)) for value in expected
        }


@pytest.mark.parametrize("token", ["floor", "maintenance"])
def test_assignment_request_permission_is_not_inferred(world, token):
    with client_for(world) as client:
        response = post(client, message(), token)
        assert response.status_code == 403
    assert count(world, "update_request") == 0


@pytest.mark.parametrize(
    "text,code,status",
    [
        (message().replace("OP20", "NOT-FOUND"), "TARGET_NOT_FOUND", 404),
        (message("EQ101,NOT-FOUND"), "TARGET_NOT_FOUND", 404),
        (message("EQ101,EQ101"), "INVALID_ARGUMENT", 400),
        (message(end=START), "BUSINESS_RULE_VIOLATION", 422),
    ],
)
def test_invalid_assignment_input_creates_no_partial_request(world, text, code, status):
    with client_for(world) as client:
        response = post(client, text)
        assert response.status_code == status
        assert response.json()["errors"][0]["code"] == code
    assert count(world, "update_request") == count(world, "graph_outbox") == 0


def test_assignment_retry_keeps_fixed_child_ids_and_rejects_changed_set(world):
    retry_headers = {**headers(), "Idempotency-Key": str(uuid4())}
    with client_for(world) as client:
        first = client.post("/agent", json={"message": message()}, headers=retry_headers)
        second = client.post("/agent", json={"message": message()}, headers=retry_headers)
        assert first.status_code == second.status_code == 200
        assert (
            first.json()["data"]["canonical_snapshot"]
            == second.json()["data"]["canonical_snapshot"]
        )
        changed = client.post("/agent", json={"message": message("EQ101")}, headers=retry_headers)
        assert changed.status_code == 409
        assert changed.json()["errors"][0]["code"] == "DUPLICATE_REQUEST"
    assert count(world, "update_request") == 1


@pytest.mark.parametrize("text", [f"「{message()}」", f"{message()}？"])
def test_quoted_assignment_and_question_are_not_update_authority(text):
    request = AgentInput.parse(
        ExecutionContext("production1", "production", uuid4()),
        json.dumps({"message": text}),
        received_at="2026-10-14T00:00:00Z",
    )
    assert production_assignment_command(request) is None


def test_private_operation_lookup_binds_sql_like_code(world):
    with world.transaction() as connection:
        assert get_operation_by_code(connection, "OP20' OR 1=1 --") is None
        assert get_operation_by_code(connection, "OP20")["production_operation_id"] == UUID(int=20)
