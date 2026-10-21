"""Natural-language target lookup preserves each real search and bounded admission."""

from uuid import uuid4

import pytest
from application.test_proposals import context

from agent.test_read_agent import ScriptedLLM, call, request
from linescope.agent.read_agent import ReadAgent
from linescope.application.reads import ReadResult, ToolError
from linescope.integrations.llm import LLMReply


class SearchDispatcher:
    def __init__(self, results):
        self.results = iter(results)
        self.arguments = []

    def schemas(self):
        return {"search_equipment": {"type": "object"}}

    def run(self, context, tool, arguments, **kwargs):
        assert tool == "search_equipment"
        self.arguments.append(arguments)
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return ReadResult(result, {"source": "POSTGRESQL"})


EMPTY = {"items": [], "next_cursor": None}


@pytest.mark.parametrize("field,other", [("name", "equipment_code"), ("equipment_code", "name")])
def test_zero_lookup_reads_the_other_condition_before_next_generation(field, other):
    target = {"equipment_id": str(uuid4())}
    dispatcher = SearchDispatcher([EMPTY, {"items": [target], "next_cursor": None}])
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {field: "literal"}, "page_size": 20}),
        LLMReply("登録された設備を確認しました。", ()),
    )
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.arguments == [
        {"filter": {field: "literal"}, "page_size": 20},
        {"filter": {other: "literal"}, "page_size": 20},
    ]
    assert [item.result.data for item in result.observations] == [
        EMPTY,
        {"items": [target], "next_cursor": None},
    ]
    assert len(result.trace) == 2 and all(row["code"] == "OK" for row in result.trace)
    assert llm.requests[1][0][-1]["role"] == "tool"
    assert len(llm.requests) == 2


@pytest.mark.parametrize(
    "arguments,data",
    [
        (
            {"filter": {"name": "literal"}},
            {"items": [{"equipment_id": "one"}], "next_cursor": None},
        ),
        ({"filter": {"name": "literal"}, "cursor": "continued"}, EMPTY),
        ({"filter": {"name": "literal", "equipment_code": "literal"}}, EMPTY),
    ],
)
def test_nonempty_continuation_and_explicit_and_filters_keep_their_meaning(arguments, data):
    dispatcher = SearchDispatcher([data])
    result = ReadAgent(
        dispatcher, ScriptedLLM(call("search_equipment", arguments), LLMReply("取得結果です。", ()))
    ).run(context(), request())
    assert dispatcher.arguments == [arguments] and len(result.observations) == 1


def test_two_empty_conditions_do_not_create_an_unbounded_cycle():
    dispatcher = SearchDispatcher([EMPTY, EMPTY])
    result = ReadAgent(
        dispatcher,
        ScriptedLLM(
            call("search_equipment", {"filter": {"name": "literal"}}), LLMReply("該当なし。", ())
        ),
    ).run(context(), request())
    assert len(dispatcher.arguments) == len(result.observations) == 2


def test_failed_lookup_is_not_treated_as_zero_results():
    dispatcher = SearchDispatcher([ToolError("INVALID_ARGUMENT", "Rejected")])
    result = ReadAgent(
        dispatcher,
        ScriptedLLM(
            call("search_equipment", {"filter": {"name": "第一加工機"}}),
            LLMReply("補足が必要です。", ()),
        ),
    ).run(context(), request())
    assert len(dispatcher.arguments) == 1 and not result.observations
    assert result.errors[0]["code"] == "INVALID_ARGUMENT"


def test_alternate_read_cannot_bypass_the_twelve_call_budget():
    dispatcher = SearchDispatcher([EMPTY] * 12)
    llm = ScriptedLLM(
        *[
            call("search_equipment", {"filter": {"name": f"第{number + 1}加工機"}})
            for number in range(7)
        ]
    )
    with pytest.raises(ToolError, match="budget") as error:
        ReadAgent(dispatcher, llm).run(context(), request())
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert len(dispatcher.arguments) == 12


@pytest.mark.parametrize(
    "records,expected",
    [
        (EMPTY, True),
        ({"items": [{"record_code": "R-1"}], "next_cursor": None}, False),
        ({"items": [], "next_cursor": "more"}, False),
    ],
)
def test_empty_record_summary_does_not_claim_a_last_date_or_leak_generated_ids(records, expected):
    from linescope.agent.read_agent import ReadObservation, supported_answer

    observations = (ReadObservation("call", "search_maintenance_records", ReadResult(records, {})),)
    answer = supported_answer(observations)
    if expected:
        assert "0件" in answer
        assert "実施されていないことを意味するものではありません" in answer
        assert supported_answer(observations, has_errors=True) is None
    else:
        assert answer is None
