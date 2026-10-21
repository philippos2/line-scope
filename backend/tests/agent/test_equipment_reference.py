"""Common read planning preserves target context, spelling, records and evidence."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest
from application.test_proposals import context

from agent.test_read_agent import ScriptedLLM, call, request
from linescope.agent.answer_text import public_answer
from linescope.agent.read_agent import ReadAgent, ReadObservation
from linescope.application.reads import ReadResult, ToolError
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
def test_name_variants_and_explicit_question_use_the_common_read_loop(registry, name):
    dispatcher = Observed(registry)
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"name": name}}),
        call("search_maintenance_records", {"filter": {"equipment_id": str(UUID(int=1))}}),
        LLMReply("記録はありません。", ()),
    )
    result = ReadAgent(dispatcher, llm).run(
        context(),
        replace(
            request(name + "の前回のメンテナンス日時はいつか？"),
            message="調査対象の設備コードはOTHERです。\n"
            + name
            + "の前回のメンテナンス日時はいつか？",
        ),
    )
    assert not result.errors and not result.needs_input
    assert "0件" in result.answer
    assert "実施されていないことを意味するものではありません" in result.answer
    assert len(llm.requests) == 3
    summary = json.loads(llm.requests[1][0][-1]["content"])["equipment_lookup_summary"]
    assert len(summary) == 1 and summary[0]["status"] == "FOUND"
    assert summary[0]["candidate_count"] == 1
    assert summary[0]["candidates"][0]["equipment_id"] == str(UUID(int=1))
    final_payloads = [json.loads(m["content"]) for m in llm.requests[-1][0] if m["role"] == "tool"]
    assert sum("equipment_lookup_summary" in payload for payload in final_payloads) == 1
    assert "search_maintenance_records" in llm.requests[0][1]
    assert llm.requests[0][0][-1] == {
        "role": "user",
        "content": name + "の前回のメンテナンス日時はいつか？",
    }
    assert all("OTHER" not in message["content"] for message in llm.requests[0][0])
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
        dispatcher,
        ScriptedLLM(
            call("search_equipment", {"filter": {"name": "第1加工機"}}),
            LLMReply("E-1とE-2の複数候補があります。設備コードを指定してください。", ()),
        ),
    ).run(context(), request("第1加工機の前回のメンテナンス日時はいつか？"))
    assert "E-1" in result.answer and "E-2" in result.answer
    assert {
        row["equipment_id"] for obs in result.observations for row in obs.result.data["items"]
    } == {str(UUID(int=1)), str(UUID(int=2))}
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

    class PagedRecordLLM(ScriptedLLM):
        def complete(self, messages, *, schemas, deadline):
            from copy import deepcopy

            self.requests.append((deepcopy(messages), schemas, deadline))
            pages = [
                json.loads(m["content"])["data"]
                for m in messages
                if m["role"] == "tool" and m["tool_name"] == "search_maintenance_records"
            ]
            if not pages:
                return call(
                    "search_maintenance_records",
                    {"filter": {"equipment_id": str(UUID(int=1))}, "page_size": 100},
                )
            if pages[-1]["next_cursor"]:
                return call(
                    "search_maintenance_records",
                    {
                        "filter": {"equipment_id": str(UUID(int=1))},
                        "page_size": 100,
                        "cursor": pages[-1]["next_cursor"],
                    },
                )
            return LLMReply("取得した記録の最新実施日時は2025-01-02T18:30:00.000000Zです。", ())

    llm = PagedRecordLLM()
    result = ReadAgent(dispatcher, llm).run(
        context(), request("E-1が最後にメンテナンスされたのはいつか？")
    )
    pages = [args for tool, args in dispatcher.calls if tool == "search_maintenance_records"]
    assert len(pages) == 2 and pages[0].get("cursor") is None and pages[1]["cursor"]
    records = [
        row for observation in result.observations for row in observation.result.data["items"]
    ]
    assert len(records) == 101 and len({row["maintenance_record_id"] for row in records}) == 101
    assert "2025/01/03 03:30:00（日本時間）" in result.answer
    assert not result.errors and len(llm.requests) == 3


def test_failed_record_read_is_not_an_absence_answer(registry):
    dispatcher = Observed(registry, fail_records=True)
    result = ReadAgent(
        dispatcher,
        ScriptedLLM(
            call("search_equipment", {"filter": {"name": "第1加工機"}}),
            call("search_maintenance_records", {"filter": {"equipment_id": str(UUID(int=1))}}),
            LLMReply("一部の登録情報を取得できませんでした。", ()),
        ),
    ).run(context(), request("第1加工機の前回のメンテナンス日時はいつか？"))
    assert result.errors and "取得できません" in result.answer and "0件" not in result.answer
    assert sum(tool == "search_maintenance_records" for tool, _ in dispatcher.calls) == 3


def test_mixed_question_retains_the_general_read_flow(registry):
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"name": "第1加工機"}}),
        LLMReply("実施内容はこの記録から判断できません。", ()),
    )
    dispatcher = Observed(registry)
    result = ReadAgent(dispatcher, llm).run(
        context(), request("第1加工機の前回のメンテナンス日時と実施内容を教えて")
    )
    assert len(llm.requests) == 2 and len(llm.requests[0][1]) > 1
    assert result.answer == "実施内容はこの記録から判断できません。"
    assert dispatcher.calls == [
        ("search_equipment", {"filter": {"name": name}})
        for name in ("第1加工機", "第一加工機", "第１加工機")
    ]


@pytest.fixture
def pair(registry):
    with registry.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'E-2','第2加工機','machine',true)",
            (UUID(int=2),),
        )
    return registry


def test_explicit_question_target_is_separate_from_selection_and_old_conversation(pair):
    question = "第２加工機の前回のメンテナンス日時はいつか？"
    incoming = replace(
        request(question),
        message="調査対象の設備コードはE-1です。\n" + question,
        context_id=str(UUID(int=99)),
    )
    dispatcher = Observed(pair)
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"name": "第２加工機"}}),
        call("search_maintenance_records", {"filter": {"equipment_id": str(UUID(int=2))}}),
        LLMReply("記録なし。", ()),
    )
    result = ReadAgent(dispatcher, llm).run(
        context(),
        incoming,
        previous_messages=["調査対象の設備コードはE-1です。\nこの設備の状態は？"],
    )
    messages = llm.requests[0][0]
    assert messages[-1] == {"role": "user", "content": question}
    assert messages[-2] == {"role": "user", "content": "この設備の状態は？"}
    assert len(messages) == 4  # system, prior selection and question, current question
    assert "E-1" not in messages[0]["content"]
    assert "0件" in result.answer and "E-2" in result.answer and "E-1" not in result.answer
    assert not result.errors
    assert [
        args["filter"] for tool, args in dispatcher.calls if tool == "search_maintenance_records"
    ] == [{"equipment_id": str(UUID(int=2))}]


def test_implicit_question_keeps_current_selection_separate_from_previous_target(pair):
    question = "この設備の前回のメンテナンス日時はいつか？"
    incoming = replace(
        request(question),
        message="調査対象の設備コードはE-2です。\n" + question,
        context_id=str(UUID(int=99)),
    )
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"equipment_code": "E-2"}}),
        call("search_maintenance_records", {"filter": {"equipment_id": str(UUID(int=2))}}),
        LLMReply("記録なし。", ()),
    )
    dispatcher = Observed(pair)
    result = ReadAgent(dispatcher, llm).run(
        context(),
        incoming,
        previous_messages=["第1加工機の前回のメンテナンス日時はいつか？"],
    )
    messages = llm.requests[0][0]
    assert messages[-1] == {"role": "user", "content": question}
    assert messages[-2]["role"] == "user" and "E-2" in messages[-2]["content"]
    assert "E-2" not in messages[0]["content"]
    assert messages[1]["content"].startswith("第1加工機")
    assert "0件" in result.answer and "E-2" in result.answer and not result.errors
    assert [
        args["filter"] for tool, args in dispatcher.calls if tool == "search_maintenance_records"
    ] == [{"equipment_id": str(UUID(int=2))}]


def test_general_multi_equipment_lookup_preserves_both_spelling_groups(pair):
    planned = (
        call("search_equipment", {"filter": {"name": "第一加工機"}}).tool_calls
        + call("search_equipment", {"filter": {"name": "第２加工機"}}).tool_calls
    )
    llm = ScriptedLLM(LLMReply("", planned), LLMReply("未確認の参照：" + str(UUID(int=999)), ()))
    dispatcher = Observed(pair)
    result = ReadAgent(dispatcher, llm).run(
        context(), request("第一加工機と第２加工機の製造メーカーは同じか？")
    )
    assert not result.errors and len(llm.requests) == 2
    assert str(UUID(int=999)) not in result.answer
    assert "内部識別子を含めずに説明できません" in result.answer
    # Verified but unnamed references stay distinct; an invented ID is never relabelled.
    unnamed = ReadObservation(
        "graph",
        "trace_upstream_dependencies",
        ReadResult({"nodes": [{"entity_id": str(UUID(int=n))} for n in (1, 2)]}, {}),
    )
    rendered = public_answer(f"{UUID(int=1)}と{UUID(int=2)}", [unnamed])
    assert rendered == "取得結果の参照1と取得結果の参照2"
    conflicting = ReadObservation(
        "read",
        "get_equipment",
        ReadResult(
            {
                "equipment_id": str(UUID(int=1)),
                "equipment_code": "E-1",
                "product_id": str(UUID(int=1)),
                "product_code": "P-1",
            },
            {},
        ),
    )
    assert "説明できません" in public_answer(str(UUID(int=1)), [conflicting])
    assert len(result.observations) == len(dispatcher.calls) == 8
    found = {
        row["equipment_id"]
        for observation in result.observations
        for row in observation.result.data["items"]
    }
    assert found == {str(UUID(int=1)), str(UUID(int=2))}
    names = {args["filter"]["name"] for _, args in dispatcher.calls if "name" in args["filter"]}
    assert names == {
        "第1加工機",
        "第一加工機",
        "第１加工機",
        "第2加工機",
        "第二加工機",
        "第２加工機",
    }
    # Both original zeroes and successful variant reads reach the next model turn.
    payloads = [
        json.loads(message["content"])
        for message in llm.requests[1][0]
        if message["role"] == "tool"
    ]
    assert len(payloads) == 8
    summaries = payloads[-1]["equipment_lookup_summary"]
    assert len(summaries) == 2
    assert all(s["status"] == "FOUND" and s["candidate_count"] == 1 for s in summaries)
    assert {s["candidates"][0]["equipment_id"] for s in summaries} == found
    assert {
        row["equipment_id"] for payload in payloads for row in payload["data"]["items"]
    } == found
    assert any(payload["data"]["items"] == [] for payload in payloads)


def test_general_lookup_keeps_distinct_equipment_for_colliding_spellings(registry):
    with registry.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'E-3','第一加工機','machine',true)",
            (UUID(int=3),),
        )
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"name": "第1加工機"}}),
        LLMReply("候補：" + str(UUID(int=1)) + "、" + str(UUID(int=3)), ()),
    )
    dispatcher = Observed(registry)
    result = ReadAgent(dispatcher, llm).run(context(), request("第1加工機の製造メーカーは？"))
    assert not result.errors and len(result.observations) == 3
    assert "E-1" in result.answer and "E-3" in result.answer
    assert str(UUID(int=1)) not in result.answer and str(UUID(int=3)) not in result.answer
    found = {
        row["equipment_id"]
        for observation in result.observations
        for row in observation.result.data["items"]
    }
    assert found == {str(UUID(int=1)), str(UUID(int=3))}
    assert all(tool == "search_equipment" for tool, _ in dispatcher.calls)
    summary = json.loads(llm.requests[1][0][-1]["content"])["equipment_lookup_summary"]
    assert len(summary) == 1 and summary[0]["status"] == "MULTIPLE_MATCHES"
    assert summary[0]["candidate_count"] == 2
    # Successful original lookup must not prevent collision checks before generation.
    payloads = [
        json.loads(message["content"])
        for message in llm.requests[1][0]
        if message["role"] == "tool"
    ]
    assert {
        row["equipment_id"] for payload in payloads for row in payload["data"]["items"]
    } == found
