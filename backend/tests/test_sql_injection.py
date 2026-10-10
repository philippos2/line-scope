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
