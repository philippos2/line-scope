"""A claim can only name a server-created fact, never reinterpret a relation."""

from uuid import UUID

import pytest
from application.test_proposals import context

from agent.test_read_agent import Dispatcher, ScriptedLLM, call, request
from linescope.agent.grounded_answer import build_answer
from linescope.agent.read_agent import ReadAgent, ReadObservation
from linescope.agent.read_scope import FIELDS, PLAN_TOOL, ReadScope
from linescope.application.reads import ReadResult, ToolError
from linescope.integrations.llm import LLMReply


def observed(tool="get_equipment", data=None, arguments=None, identifier="observed-1"):
    return ReadObservation(
        identifier,
        tool,
        ReadResult(data or {"equipment_code": "E-42"}, {"source": "POSTGRESQL"}),
        arguments,
    )


@pytest.mark.parametrize(
    "selection",
    [
        {"fact_ids": ["invented"]},
        {"fact_ids": ["f999"]},
        {"fact_ids": ["f1"], "text": "根拠と異なる主張"},
        {"fact_ids": ["f1", "f1"]},
    ],
)
def test_invalid_claim_selection_never_reaches_public_prose(selection):
    answer, sections = build_answer((observed(),), selected=selection)
    assert "E-42" in answer and "根拠と異なる主張" not in answer
    assert any(row["code"] == "INVALID_SELECTION" for row in sections["unavailable"])
    assert {ref for row in sections["facts"] for ref in row["references"]} == {"observed-1"}


def test_selection_reorders_only_server_values_and_cannot_hide_limitations():
    rows = (observed(identifier="a"), observed(data={"equipment_code": "E-99"}, identifier="b"))
    answer, sections = build_answer(
        rows, scope=ReadScope(("UNSUPPORTED",)), selected={"fact_ids": ["f2"]}
    )
    assert answer.index("E-99") < answer.index("E-42")
    assert "範囲外" in answer and len(sections["facts"]) == 2


def test_unrelated_source_field_is_not_a_supported_attribute():
    answer, sections = build_answer(
        (observed(data={"equipment_code": "E-42", "untrusted_property": "架空の場所"}),),
        scope=ReadScope(("UNSUPPORTED",)),
    )
    assert "架空の場所" not in answer and "登録がありません" not in answer
    assert sections["unavailable"][0]["code"] == "OUT_OF_SCOPE"


def test_unrendered_relation_cannot_become_another_predicate():
    item = observed(
        "get_dependency_relation",
        {
            "relation_type": "SUPPLIES",
            "source_entity_id": str(UUID(int=8)),
            "target_entity_id": str(UUID(int=42)),
        },
    )
    answer, sections = build_answer((item,), scope=ReadScope(("UPSTREAM", "UNSUPPORTED")))
    assert "保管" not in answer and not sections["facts"]
    assert {row["code"] for row in sections["unavailable"]} == {
        "NO_PUBLIC_RENDERER",
        "OUT_OF_SCOPE",
    }


def test_partial_search_is_not_zero_or_latest():
    item = observed(
        "search_maintenance_records",
        {"items": [], "next_cursor": "pending"},
        {"filter": {"equipment_id": str(UUID(int=42))}},
    )
    answer, sections = build_answer((item,), scope=ReadScope(("MAINTENANCE",)))
    assert "0件" not in answer and "続き" in answer
    assert any(row["code"] == "INCOMPLETE" for row in sections["unavailable"])


def test_read_failure_never_means_absence():
    answer, sections = build_answer(
        (observed(),),
        errors=({"code": "DEPENDENCY_UNAVAILABLE"},),
        scope=ReadScope(("MAINTENANCE",)),
    )
    assert "取得できません" in answer and "0件" not in answer
    assert {row["code"] for row in sections["unavailable"]} == {"READ_FAILED", "NOT_RETRIEVED"}


class ScopedLLM(ScriptedLLM):
    def __init__(self, topics, *replies):
        super().__init__(*replies)
        self.topics = topics

    def complete(self, messages, *, schemas, deadline):
        if PLAN_TOOL in schemas:
            self.planning_requests.append((messages, schemas, deadline))
            return call(
                PLAN_TOOL,
                {
                    "topics": self.topics,
                    "subjects": [],
                    "requested_fields": [
                        next(
                            (field for field, topic in FIELDS.items() if topic == chosen),
                            "unsupported",
                        )
                        for chosen in self.topics
                    ],
                },
            )
        return super().complete(messages, schemas=schemas, deadline=deadline)


def test_scope_reduces_advertised_tools_without_expanding_authority():
    llm = ScopedLLM(["ATTRIBUTES", "UNSUPPORTED"], call(), LLMReply("値を推測した自由な回答", ()))
    result = ReadAgent(Dispatcher(), llm).run(context(), request())
    assert "get_equipment" in llm.requests[0][1]
    assert "get_equipment_state" not in llm.requests[0][1]
    assert "prepare_equipment_state_update" not in llm.requests[0][1]
    assert "値を推測した自由な回答" not in result.answer
    assert "範囲外" in result.answer and "M-204" in result.answer
    assert llm.planning_requests[0][2] == llm.requests[0][2]


def test_scope_runtime_rejects_provider_call_outside_advertised_capability():
    dispatcher = Dispatcher()
    llm = ScopedLLM(["ATTRIBUTES"], call("get_equipment_state"), LLMReply("停止中です", ()))
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 0
    assert result.errors[0]["code"] == "AUTHORIZATION_DENIED"
    assert "停止中です" not in result.answer


def test_invalid_scope_never_dispatches_or_defaults_to_all_tools():
    dispatcher = Dispatcher()
    with pytest.raises(ToolError) as error:
        ReadAgent(dispatcher, ScopedLLM(["nonexistent"])).run(context(), request())
    assert error.value.code == "INTERNAL_ERROR" and dispatcher.calls == 0


def test_valid_selection_has_only_actual_request_references():
    llm = ScopedLLM(["ATTRIBUTES"], call(), call("select_answer_facts", {"fact_ids": ["f1"]}))
    result = ReadAgent(Dispatcher(), llm).run(context(), request())
    assert result.answer_sections["facts"][0]["references"] == [result.observations[0].tool_call_id]
    assert result.answer_sections["facts"][0]["predicate"] == "equipment.registered_fields"


def test_display_limit_is_explicit_and_not_completed_as_a_global_claim():
    data = {
        "items": [
            {"equipment_code": f"E-{n}", "equipment_id": str(UUID(int=n + 1))} for n in range(81)
        ],
        "next_cursor": None,
    }
    _, sections = build_answer((observed("search_equipment", data, {"filter": {}}),))
    assert len(sections["facts"]) == 80
    assert any(row["code"] == "DISPLAY_LIMIT" for row in sections["unavailable"])
