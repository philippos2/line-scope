"""BS-14/19 API semantics with real storage and explicit developer-owned fixtures.

ScriptedLLM fixes the initial read call, not authorization or mutation results.
BS-14 uses the supported explicit command variant, not arbitrary Japanese.
"""

import pytest
from agent.test_read_agent import ScriptedLLM, call
from fastapi.testclient import TestClient
from graph.test_alternative_facts import M
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from sqlalchemy import column, func, select, table, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.settings import Settings


def query(db, statement):
    compiled = statement.compile(dialect=dialect())
    with db.transaction() as connection:
        result = connection.execute(str(compiled), compiled.params)
        return result.fetchall() if statement.is_select else None


def headers(token="requester"):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def running_world(db, reader_world):
    state = table(
        "equipment_current_state",
        column("equipment_id", PGUUID()),
        column("state_code"),
        column("version"),
    )
    query(
        db,
        update(state).where(state.c.equipment_id == M[1]).values(state_code="RUNNING", version=10),
    )
    return state


def client_for(db, driver, llm):
    settings = Settings(
        users={
            "requester": {"user_id": "maint1", "role": "maintenance"},
            "approver": {"user_id": "maint2", "role": "maintenance"},
        }
    )
    return TestClient(create_app(settings, db, llm=llm, graph_driver=driver))


def prepare(client, state):
    response = client.post(
        "/agent", json={"message": f"設備M-204の状態を{state}に変更して"}, headers=headers()
    )
    assert response.status_code == 200
    return response.json()["data"]


def approve_execute(client, saved):
    approval = client.post(
        f"/approvals/{saved['approval_id']}/approve",
        json={"snapshot_hash": saved["snapshot_hash"]},
        headers=headers("approver"),
    )
    assert approval.status_code == 200
    execution = client.post(
        f"/update-requests/{saved['update_request_id']}/execute", headers=headers()
    )
    assert execution.status_code == 200
    return execution.json()["data"]


def counts(db):
    return {
        name: query(db, select(func.count().label("n")).select_from(table(name)))[0]["n"]
        for name in ("business_update_history", "equipment_state_history", "graph_outbox")
    }


@pytest.mark.parametrize(
    "message",
    [
        "設備M-204の状態をUNDER_MAINTENANCEに変更して",
        "M-204の現在状態をUNDER_MAINTENANCEに変更する準備を作って",
    ],
)
def test_bs14_analysis_then_explicit_prepare_keeps_current_state_unchanged(
    db, running_world, adapters, message
):
    """Given maintenance reviewed analysis of RUNNING version 10;
    When explicitly requesting the supported update command;
    Then prepare PENDING approval and fixed before/after, without execution.
    """
    llm = ScriptedLLM(
        call("trace_downstream_impact", {"target": {"entity_type": M[0], "entity_id": M[1]}}),
        LLMReply("依存関係を確認しました。実際の停止影響は未評価です。", ()),
    )
    with client_for(db, adapters[1].driver, llm) as client:
        analysis = client.post("/agent", json={"message": "M-204の影響を調べて"}, headers=headers())
        assert analysis.status_code == 200
        assert (
            analysis.json()["evidence"]["tool_results"][0]["state_versions"]["Equipment:" + M[1]]
            == 10
        )
        response = client.post("/agent", json={"message": message}, headers=headers())
        assert response.status_code == 200
        saved = response.json()["data"]
        snapshot = saved["canonical_snapshot"]
        assert saved["status"] == "WAITING_APPROVAL" and saved["approval_status"] == "PENDING"
        assert saved["update_request_id"] and saved["approval_id"] and saved["snapshot_hash"]
        target = snapshot["targets"][0]
        assert len(snapshot["targets"]) == 1
        assert target["before"]["state_code"] == "RUNNING" and target["before"]["version"] == 10
        assert (
            target["after"]["state_code"] == "UNDER_MAINTENANCE"
            and target["after"]["version"] == 11
        )
        assert (
            client.post(
                f"/update-requests/{saved['update_request_id']}/execute", headers=headers()
            ).status_code
            == 409
        )
    assert len(llm.requests) == 2  # Analysis only; Prepare did not ask the LLM to act.
    assert counts(db) == {
        "business_update_history": 0,
        "equipment_state_history": 0,
        "graph_outbox": 0,
    }
    current = query(db, select(running_world).where(running_world.c.equipment_id == M[1]))[0]
    assert current["state_code"] == "RUNNING" and current["version"] == 10


def test_bs19_confirmed_after_is_preserved_after_later_authorized_update_and_replay(
    db, running_world, adapters
):
    """Given two independently approved and requester-executed changes;
    When inspecting/replaying the first request after the second commits;
    Then distinguish confirmed v11/current v12 without duplicate changes.
    """
    llm = ScriptedLLM()
    with client_for(db, adapters[1].driver, llm) as client:
        first = prepare(client, "UNDER_MAINTENANCE")
        confirmed = approve_execute(client, first)
        second = prepare(client, "RUNNING")
        later = approve_execute(client, second)
        assert later["current_snapshot"]["targets"][0]["snapshot"]["version"] == 12
        before = counts(db)
        assert before["business_update_history"] == before["equipment_state_history"] == 2
        observed = client.get(
            f"/update-requests/{first['update_request_id']}", headers=headers()
        ).json()["data"]
        replay = client.post(
            f"/update-requests/{first['update_request_id']}/execute", headers=headers()
        ).json()["data"]
        for result in (observed, replay):
            assert result["status"] == "COMPLETED" and result["approval_status"] == "CONSUMED"
            assert result["execution_result"] == confirmed["execution_result"]
            assert (
                result["execution_result"]["targets"][0]["after"]["state_code"]
                == "UNDER_MAINTENANCE"
            )
            assert result["execution_result"]["targets"][0]["after"]["version"] == 11
        current = replay["current_snapshot"]["targets"][0]["snapshot"]
        assert current["state_code"] == "RUNNING" and current["version"] == 12
        assert replay["current_versions"][0]["version_delta"] == 1
        assert counts(db) == before
    assert not llm.requests
