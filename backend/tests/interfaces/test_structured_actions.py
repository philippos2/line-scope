"""Explicit structured Prepare through public API and existing update services."""

import json
from uuid import uuid4

import pytest
from application.test_tools import database as database
from application.test_tools import inputs
from fastapi.testclient import TestClient
from sqlalchemy import func, select, table

from interfaces.test_controlled_action_scenarios import approve_execute, counts, headers, query
from linescope.interfaces.api import create_app
from linescope.settings import Settings


def client_for(database, role="manager"):
    return TestClient(
        create_app(
            Settings(
                users={
                    "requester": {"user_id": "manager1", "role": role},
                    "approver": {"user_id": "manager2", "role": "manager"},
                }
            ),
            database,
        )
    )


def message(label, targets):
    return (
        label + "の変更準備を" + json.dumps({"targets": targets}, ensure_ascii=False) + "で作成して"
    )


def target(tool):
    return {"prepare_tool": tool, "input": inputs()[tool]}


@pytest.mark.parametrize(
    "label,tool",
    [
        ("設備状態", "prepare_equipment_state_update"),
        ("保全", "prepare_maintenance_plan_update"),
        ("生産作業", "prepare_production_operation_update"),
        ("依存関係", "prepare_dependency_relation_update"),
    ],
)
def test_each_category_flows_from_explicit_json_to_approved_execution(database, label, tool):
    with client_for(database) as client:
        response = client.post(
            "/agent", json={"message": message(label, [target(tool)])}, headers=headers()
        )
        assert response.status_code == 200
        saved = response.json()["data"]
        assert saved["status"] == "WAITING_APPROVAL"
        assert counts(database)["business_update_history"] == 0
        executed = approve_execute(client, saved)
        assert executed["status"] == "COMPLETED"
        assert executed["execution_result"]["targets"] == saved["canonical_snapshot"]["targets"]
        assert counts(database)["business_update_history"] == 1


def test_same_category_plan_and_record_are_one_request_with_durable_retry(database):
    targets = [
        target("prepare_maintenance_plan_update"),
        target("prepare_maintenance_record_create"),
    ]
    body = {"message": message("保全", targets)}
    retry_headers = {**headers(), "Idempotency-Key": str(uuid4())}
    with client_for(database) as client:
        response = client.post("/agent", json=body, headers=retry_headers)
        assert response.status_code == 200
        saved = response.json()["data"]
        assert len(saved["canonical_snapshot"]["targets"]) == 2
        approve_execute(client, saved)
        before = counts(database)
        retried = client.post("/agent", json=body, headers=retry_headers)
        assert retried.status_code == 200
        assert retried.json()["data"]["canonical_snapshot"] == saved["canonical_snapshot"]
        assert counts(database) == before


@pytest.mark.parametrize(
    "label,targets,status",
    [
        (
            "設備状態",
            [target("prepare_equipment_state_update"), target("prepare_maintenance_plan_update")],
            422,
        ),
        ("設備状態", [{"prepare_tool": "execute", "input": {}}], 400),
        (
            "設備状態",
            [
                {
                    "prepare_tool": "prepare_equipment_state_update",
                    "input": {**inputs()["prepare_equipment_state_update"], "expected_version": 1},
                }
            ],
            400,
        ),
        ("設備状態", [target("prepare_equipment_state_update")] * 11, 400),
    ],
)
def test_invalid_structured_request_cannot_mutate_or_create_partial_history(
    database, label, targets, status
):
    with client_for(database) as client:
        response = client.post(
            "/agent", json={"message": message(label, targets)}, headers=headers()
        )
    assert response.status_code == status
    assert counts(database)["business_update_history"] == 0
    assert (
        query(database, select(func.count().label("n")).select_from(table("update_request")))[0][
            "n"
        ]
        == 0
    )


def test_structured_input_cannot_grant_category_permission(database):
    with client_for(database, "floor") as client:
        response = client.post(
            "/agent",
            json={"message": message("保全", [target("prepare_maintenance_plan_update")])},
            headers=headers(),
        )
    assert response.status_code == 403
    assert (
        query(database, select(func.count().label("n")).select_from(table("update_request")))[0][
            "n"
        ]
        == 0
    )
