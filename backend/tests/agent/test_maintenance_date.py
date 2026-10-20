"""A focused date question resolves real records with one bounded model plan."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from application.test_proposals import context

from agent.test_read_agent import ScriptedLLM, call, request
from linescope.agent.read_agent import ReadAgent
from linescope.application.reads import ToolError
from linescope.application.tools import ToolDispatcher
from linescope.integrations.llm import LLMReply


@pytest.fixture
def registry(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'E-1','第1加工機','machine',true)",
            (UUID(int=1),),
        )
    return db


class Observed:
    def __init__(self, db, fail_records=False):
        self.delegate = ToolDispatcher(db)
        self.calls = []
        self.fail_records = fail_records

    def schemas(self):
        return self.delegate.schemas()

    def run(self, context, tool, arguments, **kwargs):
        self.calls.append((tool, arguments))
        if tool == "search_maintenance_records" and self.fail_records:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "Fixed dependency failure")
        return self.delegate.run(context, tool, arguments, **kwargs)


@pytest.mark.parametrize("name", ["第1加工機", "第一加工機", "第１加工機"])
def test_name_variants_resolve_one_equipment_without_repeated_generation(registry, name):
    dispatcher = Observed(registry)
    llm = ScriptedLLM(call("search_equipment", {"filter": {"name": name}}))
    result = ReadAgent(dispatcher, llm).run(
        context(), request(name + "の前回のメンテナンス日時はいつか？")
    )
    assert not result.errors and not result.needs_input
    assert "第1加工機 · E-1" in result.answer and "0件" in result.answer
    assert "未実施という意味ではありません" in result.answer
    assert len(llm.requests) == 1
    assert set(llm.requests[0][1]) == {"search_equipment"}
    records = [args for tool, args in dispatcher.calls if tool == "search_maintenance_records"]
    assert len(records) == 1 and records[0]["filter"] == {"equipment_id": str(UUID(int=1))}
    assert {
        args["filter"]["name"]
        for tool, args in dispatcher.calls
        if "name" in args.get("filter", {})
    } == {"第1加工機", "第一加工機", "第１加工機"}


def test_equivalent_names_on_distinct_equipment_require_selection(registry):
    with registry.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'E-2','第一加工機','machine',true)",
            (UUID(int=2),),
        )
    dispatcher = Observed(registry)
    result = ReadAgent(
        dispatcher, ScriptedLLM(call("search_equipment", {"filter": {"name": "第1加工機"}}))
    ).run(context(), request("第1加工機の前回のメンテナンス日時はいつか？"))
    assert result.needs_input and "E-1" in result.answer and "E-2" in result.answer
    assert all(tool == "search_equipment" for tool, _ in dispatcher.calls)


def test_latest_date_uses_every_record_page_and_renders_japan_time(registry):
    with registry.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO maintenance_record(maintenance_record_id,record_code,equipment_id,performed_at,result) VALUES(%s,%s,%s,%s,'done')",
                [
                    (
                        UUID(int=n),
                        f"R-{n}",
                        UUID(int=1),
                        datetime(2025, 1, 2 if n == 101 else 1, 18, 30, tzinfo=timezone.utc),
                    )
                    for n in range(1, 102)
                ],
            )
    dispatcher = Observed(registry)
    llm = ScriptedLLM(call("search_equipment", {"filter": {"equipment_code": "E-1"}}))
    result = ReadAgent(dispatcher, llm).run(
        context(), request("E-1が最後にメンテナンスされたのはいつか？")
    )
    pages = [args for tool, args in dispatcher.calls if tool == "search_maintenance_records"]
    assert len(pages) == 2 and pages[0]["cursor"] is None and pages[1]["cursor"]
    assert "2025/01/03 03:30:00（日本時間）" in result.answer
    assert not result.errors and len(llm.requests) == 1


def test_failed_record_read_is_not_an_absence_answer(registry):
    dispatcher = Observed(registry, fail_records=True)
    result = ReadAgent(
        dispatcher, ScriptedLLM(call("search_equipment", {"filter": {"name": "第1加工機"}}))
    ).run(context(), request("第1加工機の前回のメンテナンス日時はいつか？"))
    assert result.errors and "取得できず" in result.answer and "0件" not in result.answer
    assert sum(tool == "search_maintenance_records" for tool, _ in dispatcher.calls) == 3


def test_mixed_question_retains_the_general_read_flow(registry):
    llm = ScriptedLLM(
        LLMReply("通常調査", ()),
        call("search_equipment", {"filter": {"name": "第1加工機"}}),
        LLMReply("実施内容はこの記録から判断できません。", ()),
    )
    dispatcher = Observed(registry)
    result = ReadAgent(dispatcher, llm).run(
        context(), request("第1加工機の前回のメンテナンス日時と実施内容を教えて")
    )
    assert len(llm.requests) == 3 and len(llm.requests[1][1]) > 1
    assert result.answer == "実施内容はこの記録から判断できません。"
    assert dispatcher.calls == [
        ("search_equipment", {"filter": {"name": name}})
        for name in ("第1加工機", "第一加工機", "第１加工機")
    ]
