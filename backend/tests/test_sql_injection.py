"""Attack strings remain literal values through real PostgreSQL and Agent HTTP."""

import io
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from test_agent_api import HEADERS, settings
from test_read_agent import ScriptedLLM, call
from test_search_reads import identity
from test_search_reads import search_world as search_fixture

from linescope.api import create_app
from linescope.llm import LLMReply
from linescope.logging import EventLogger
from linescope.reads import ReadTools, ToolError

ATTACKS = ["' OR 1=1 --", "'; DROP TABLE equipment; --"]
TABLES = (
    "equipment",
    "maintenance_plan",
    "maintenance_record",
    "dependency_relation",
    "update_request",
    "approval",
    "update_audit_event",
    "business_update_history",
    "graph_outbox",
)


def snapshot(db):
    with db.transaction() as c:
        return {
            table: c.execute(
                sql.SQL("SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text").format(
                    sql.Identifier(table)
                )
            ).fetchall()
            for table in TABLES
        }


@pytest.fixture
def world(db):
    return search_fixture.__wrapped__(db)


@pytest.mark.parametrize("attack", ATTACKS)
@pytest.mark.parametrize(
    "tool,field",
    [
        ("search_equipment", "name"),
        ("search_equipment", "equipment_code"),
        ("search_maintenance_plans", "plan_code"),
        ("search_maintenance_records", "record_code"),
    ],
)
def test_attack_is_a_literal_search_value_and_does_not_mutate(world, tool, field, attack):
    before = snapshot(world)
    result = ReadTools(world).run(identity(), tool, {"filter": {field: attack}})
    assert result.data == {"items": [], "next_cursor": None}
    assert snapshot(world) == before


@pytest.mark.parametrize("attack", ATTACKS)
def test_persisted_attack_is_searchable_without_second_order_execution(world, attack):
    with world.transaction() as c:
        c.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,%s,%s,'machine',true)",
            (UUID(int=99), attack, attack),
        )
    before = snapshot(world)
    reads = ReadTools(world)
    for field in ("name", "equipment_code"):
        result = reads.run(identity(), "search_equipment", {"filter": {field: attack}})
        assert [r["equipment_id"] for r in result.data["items"]] == [str(UUID(int=99))]
        assert result.data["next_cursor"] is None
    assert snapshot(world) == before


@pytest.mark.parametrize("attack", ATTACKS)
def test_untrusted_llm_arguments_through_http_do_not_change_sql_structure(world, attack):
    before = snapshot(world)
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"name": attack}}),
        LLMReply("該当設備はありません。", ()),
    )
    with TestClient(
        create_app(settings(), world, llm=llm, event_logger=EventLogger(stream=io.StringIO()))
    ) as client:
        response = client.post("/agent", headers=HEADERS, json={"message": "設備を検索して"})
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert response.json()["data"]["tool_results"][0]["data"] == {"items": [], "next_cursor": None}
    assert snapshot(world) == before


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("search_equipment; DROP TABLE equipment; --", {}),
        ("search_equipment", {"filter": {"name) OR 1=1 --": "x"}}),
        ("search_equipment", {"order_by": "equipment_code; DROP TABLE equipment; --"}),
        ("search_equipment", {"filter": {"sql": "SELECT * FROM equipment"}}),
        ("get_equipment", {"equipment_id": "' OR 1=1 --"}),
    ],
)
def test_sql_and_identifier_injection_arguments_are_rejected(world, tool, arguments):
    before = snapshot(world)
    with pytest.raises(ToolError) as caught:
        ReadTools(world).run(identity(), tool, arguments)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert snapshot(world) == before


@pytest.mark.parametrize("attack", ATTACKS)
def test_untrusted_plan_code_survives_prepare_human_execute_and_reread(db, attack):
    from uuid import uuid4

    from test_maintenance_plan_approval_api import act, client_for
    from test_maintenance_plan_create_api import execute
    from test_maintenance_prepare import AGENT_HASH, create_plan
    from test_maintenance_prepare import identity as maintenance_identity
    from test_maintenance_prepare import service as maintenance_fixture

    from linescope.tools import ToolDispatcher

    db, _ = maintenance_fixture.__wrapped__(db)
    before = snapshot(db)
    arguments = create_plan(attack)["input"]
    saved = ToolDispatcher(db).run(
        maintenance_identity(),
        "prepare_maintenance_plan_create",
        arguments,
        retry_key=uuid4(),
        agent_input_hash=AGENT_HASH,
    )
    target = saved.snapshot.data["targets"][0]
    assert target["after"]["plan_code"] == target["business_key"]["plan_code"] == attack
    prepared = snapshot(db)
    for table in (
        "equipment",
        "maintenance_plan",
        "maintenance_record",
        "dependency_relation",
        "business_update_history",
        "graph_outbox",
    ):
        assert prepared[table] == before[table]
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert snapshot(db)["maintenance_plan"] == before["maintenance_plan"]
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "ok"
        confirmed = response.json()["data"]["execution_result"]
        assert confirmed["targets"] == saved.snapshot.data["targets"]
        assert (
            response.json()["data"]["current_snapshot"]["targets"][0]["snapshot"]["plan_code"]
            == attack
        )
        committed = snapshot(db)
        found = ReadTools(db).run(
            maintenance_identity(), "search_maintenance_plans", {"filter": {"plan_code": attack}}
        )
        assert [r["maintenance_plan_id"] for r in found.data["items"]] == [target["target_id"]]
        assert found.data["items"][0]["plan_code"] == attack
        replay = execute(client, saved)
        assert replay.status_code == 200
        assert replay.json()["data"]["execution_result"] == confirmed
        assert snapshot(db) == committed
    for table in ("equipment", "maintenance_record", "dependency_relation", "graph_outbox"):
        assert committed[table] == before[table]
    plans = [r["row"] for r in committed["maintenance_plan"]]
    assert len(plans) == len(before["maintenance_plan"]) + 1
    assert [
        r
        for r in committed["maintenance_plan"]
        if r["row"]["maintenance_plan_id"] != target["target_id"]
    ] == before["maintenance_plan"]
    assert len(committed["business_update_history"]) == 1
    history = committed["business_update_history"][0]["row"]
    assert history["after_snapshot"]["targets"][0]["snapshot"]["plan_code"] == attack
    assert len(committed["update_request"]) == len(committed["approval"]) == 1
    assert committed["update_request"][0]["row"]["status"] == "COMPLETED"
    assert committed["approval"][0]["row"]["status"] == "CONSUMED"
    assert {r["row"]["action"] for r in committed["update_audit_event"]} == {
        "PREPARE",
        "APPROVE",
        "EXECUTE",
    }
    assert len(committed["update_audit_event"]) == 3


@pytest.mark.parametrize("attack", ATTACKS)
@pytest.mark.parametrize("field", ["record_code", "result"])
def test_untrusted_record_text_survives_human_execution(db, attack, field):
    from uuid import uuid4

    from test_maintenance_plan_approval_api import act, client_for
    from test_maintenance_prepare import AGENT_HASH, create_record
    from test_maintenance_prepare import identity as maintenance_identity
    from test_maintenance_prepare import service as maintenance_fixture
    from test_maintenance_record_create_api import execute

    from linescope.tools import ToolDispatcher

    db, _ = maintenance_fixture.__wrapped__(db)
    before = snapshot(db)
    arguments = create_record()["input"]
    arguments[field] = attack
    saved = ToolDispatcher(db).run(
        maintenance_identity(),
        "prepare_maintenance_record_create",
        arguments,
        retry_key=uuid4(),
        agent_input_hash=AGENT_HASH,
    )
    target = saved.snapshot.data["targets"][0]
    assert target["after"][field] == attack
    unchanged = (
        "equipment",
        "maintenance_plan",
        "maintenance_record",
        "dependency_relation",
        "business_update_history",
        "graph_outbox",
    )
    prepared = snapshot(db)
    assert all(prepared[table] == before[table] for table in unchanged)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        approved = snapshot(db)
        assert all(approved[table] == before[table] for table in unchanged)
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "ok"
        data = response.json()["data"]
        assert data["execution_result"]["targets"] == saved.snapshot.data["targets"]
        assert data["current_snapshot"]["targets"][0]["snapshot"][field] == attack
        committed = snapshot(db)
        found = ReadTools(db).run(
            maintenance_identity(),
            "search_maintenance_records",
            {"filter": {"record_code": arguments["record_code"]}},
        )
        assert [row["maintenance_record_id"] for row in found.data["items"]] == [
            target["target_id"]
        ]
        assert found.data["items"][0][field] == attack
        replay = execute(client, saved)
        assert replay.status_code == 200
        assert replay.json()["data"]["execution_result"] == data["execution_result"]
        assert snapshot(db) == committed
    for table in ("equipment", "maintenance_plan", "dependency_relation", "graph_outbox"):
        assert committed[table] == before[table]
    assert len(committed["maintenance_record"]) == 1
    assert committed["maintenance_record"][0]["row"]["maintenance_record_id"] == target["target_id"]
    assert committed["maintenance_record"][0]["row"][field] == attack
    assert len(committed["business_update_history"]) == 1
    history = committed["business_update_history"][0]["row"]
    assert history["after_snapshot"]["targets"][0]["snapshot"] == target["after"]
    assert len(committed["update_request"]) == len(committed["approval"]) == 1
    assert committed["update_request"][0]["row"]["status"] == "COMPLETED"
    assert committed["approval"][0]["row"]["status"] == "CONSUMED"
    assert {row["row"]["action"] for row in committed["update_audit_event"]} == {
        "PREPARE",
        "APPROVE",
        "EXECUTE",
    }
    assert len(committed["update_audit_event"]) == 3
