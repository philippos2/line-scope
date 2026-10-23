"""Natural-language target lookup preserves each real search and bounded admission."""

import json
from uuid import uuid4

import pytest
from application.test_proposals import context

from agent.test_read_agent import AdmittedPlanAgent, ScriptedLLM, call, request
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


def lookup_summary(llm):
    return json.loads(llm.requests[-1][0][-1]["content"])["equipment_lookup_summary"]


@pytest.mark.parametrize("field", ["name", "equipment_code"])
def test_zero_lookup_uses_shared_search_before_next_generation(field):
    target = {"equipment_id": str(uuid4())}
    dispatcher = SearchDispatcher([EMPTY, {"items": [target], "next_cursor": None}])
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {field: "literal"}, "page_size": 20}),
        LLMReply("登録された設備を確認しました。", ()),
    )
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.arguments == [
        {"filter": {field: "literal"}, "page_size": 20},
        {"filter": {"reference": "literal"}, "page_size": 20},
    ]
    assert [item.result.data for item in result.observations] == [
        EMPTY,
        {"items": [target], "next_cursor": None},
    ]
    assert len(result.trace) == 2 and all(row["code"] == "OK" for row in result.trace)
    assert llm.requests[1][0][-1]["role"] == "tool"
    assert len(llm.requests) == 2
    summary = lookup_summary(llm)
    assert len(summary) == 1 and summary[0]["status"] == "FOUND"
    assert summary[0]["equipment_found"] and summary[0]["candidate_count"] == 1
    assert summary[0]["candidates"][0]["equipment_id"] == target["equipment_id"]
    assert len(summary[0]["queries"]) == 2


@pytest.mark.parametrize(
    "arguments,data",
    [
        (
            {"filter": {"name": "literal"}, "page_size": 100},
            {"items": [{"equipment_id": f"item-{n}"} for n in range(21)], "next_cursor": None},
        ),
        ({"filter": {"name": "literal"}, "cursor": "continued"}, EMPTY),
        ({"filter": {"name": "literal", "equipment_code": "literal"}}, EMPTY),
    ],
)
def test_nonempty_continuation_and_explicit_and_filters_keep_their_meaning(arguments, data):
    # A successful strict first page must also check normalized collisions.
    expected = [arguments]
    if "cursor" not in arguments and list(arguments["filter"]) == ["name"]:
        expected.append({**arguments, "filter": {"reference": arguments["filter"]["name"]}})
    dispatcher = SearchDispatcher([data] * len(expected))
    llm = ScriptedLLM(call("search_equipment", arguments), LLMReply("取得結果です。", ()))
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.arguments == expected and len(result.observations) == len(expected)
    summary = lookup_summary(llm)[0]
    if arguments.get("cursor"):
        assert summary["status"] == "INCOMPLETE" and not summary["complete"]
    elif data["items"]:
        assert summary["status"] == "MULTIPLE_MATCHES" and summary["candidate_count"] == 21
        assert summary["candidate_sample_truncated"] and len(summary["candidates"]) == 20
        assert len(result.observations[0].result.data["items"]) == 21
        assert summary["queries"][0]["returned_equipment_count"] == 21
        assert summary["queries"][0]["returned_equipment_sample_truncated"]
    else:
        assert summary["status"] == "NO_MATCH"
        assert summary["queries"][0]["filter"] == arguments["filter"]


def test_two_empty_conditions_do_not_create_an_unbounded_cycle():
    dispatcher = SearchDispatcher([EMPTY, EMPTY])
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"name": "literal"}}), LLMReply("該当なし。", ())
    )
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert len(dispatcher.arguments) == len(result.observations) == 2
    assert lookup_summary(llm)[0]["status"] == "NO_MATCH"
    assert not lookup_summary(llm)[0]["equipment_found"]


def test_failed_lookup_is_not_treated_as_zero_results():
    dispatcher = SearchDispatcher([ToolError("INVALID_ARGUMENT", "Rejected")])
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"name": "第一加工機"}}),
        LLMReply("補足が必要です。", ()),
    )
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert len(dispatcher.arguments) == 1 and not result.observations
    assert result.errors[0]["code"] == "INVALID_ARGUMENT"
    assert lookup_summary(llm)[0]["status"] == "INCOMPLETE"
    assert not lookup_summary(llm)[0]["complete"]


def test_alternate_read_cannot_bypass_the_twelve_call_budget():
    dispatcher = SearchDispatcher([EMPTY] * 12)
    llm = ScriptedLLM(
        *[
            call("search_equipment", {"filter": {"name": f"第{number + 1}加工機"}})
            for number in range(7)
        ]
    )
    with pytest.raises(ToolError, match="budget") as error:
        AdmittedPlanAgent(dispatcher, llm).run(context(), request())
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
