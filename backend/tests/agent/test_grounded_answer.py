"""A claim can only name a server-created fact, never reinterpret a relation."""

from uuid import UUID

import pytest
from application.test_proposals import context

from agent.test_read_agent import Dispatcher, ScriptedLLM, call, request
from linescope.agent.grounded_answer import build_answer
from linescope.agent.read_agent import ReadAgent, ReadObservation
from linescope.agent.read_scope import FIELDS, PLAN_TOOL, ReadScope
from linescope.agent.scope_check import CHECK_TOOL, FIELD_MEANINGS
from linescope.application.reads import ReadResult, ToolError
from linescope.integrations.llm import LLMError, LLMReply


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
    class Pending(Dispatcher):
        def schemas(self):
            return {
                "search_equipment": {"type": "object"},
                "search_maintenance_records": {"type": "object"},
            }

        def run(self, context, tool, arguments, **kwargs):
            assert tool == "search_equipment"
            self.calls += 1
            return ReadResult({"items": [], "next_cursor": "pending" + str(self.calls)}, {})

    llm = ScopedLLM(["MAINTENANCE"], subjects=({"entity_type": "Equipment", "reference": "M-204"},))
    dispatcher = Pending()
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert "0件" not in result.answer and "続き" in result.answer
    assert any(row["code"] == "INCOMPLETE" for row in result.answer_sections["unavailable"])
    assert any(row["code"] == "AGENT_LIMIT_REACHED" for row in result.errors)
    assert dispatcher.calls == 12 and len(result.observations) == 12
    assert len(llm.planning_requests) == 1 and not llm.requests
    assert "抽出した対象表現：M-204" in result.answer_sections["scope"]


def test_read_failure_never_means_absence():
    answer, sections = build_answer(
        (observed(),),
        errors=({"code": "DEPENDENCY_UNAVAILABLE"},),
        scope=ReadScope(("MAINTENANCE",)),
    )
    assert "取得できません" in answer and "0件" not in answer
    assert {row["code"] for row in sections["unavailable"]} == {"READ_FAILED", "NOT_RETRIEVED"}


class ScopedLLM(ScriptedLLM):
    def __init__(self, topics, *replies, subjects=()):
        super().__init__(*replies)
        self.topics = topics
        self.subjects = list(subjects)

    def complete(self, messages, *, schemas, deadline):
        if PLAN_TOOL in schemas:
            self.planning_requests.append((messages, schemas, deadline))
            return call(
                PLAN_TOOL,
                {
                    "topics": self.topics,
                    "subjects": self.subjects,
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
    class Lookup(Dispatcher):
        def run(self, context, tool, arguments, **kwargs):
            self.calls += 1
            assert tool == "search_equipment"
            assert context.authenticated_user_id == "floor1"
            matched = arguments["filter"] == {"equipment_code": "M-204"}
            return ReadResult(
                {
                    "items": [{"equipment_id": str(UUID(int=1)), "equipment_code": "M-204"}]
                    if matched
                    else [],
                    "next_cursor": None,
                },
                {"source": "POSTGRESQL"},
            )

        def schemas(self):
            return {
                name: {"type": "object"}
                for name in (
                    "search_equipment",
                    "get_equipment",
                    "get_equipment_state",
                    "prepare_equipment_state_update",
                )
            }

    llm = ScopedLLM(
        ["ATTRIBUTES", "UNSUPPORTED"],
        LLMReply("値を推測した自由な回答", ()),
        subjects=({"entity_type": "Equipment", "reference": "M-204"},),
    )
    dispatcher = Lookup()
    result = ReadAgent(dispatcher, llm).run(context(), request())
    advertised = ReadScope(("ATTRIBUTES", "UNSUPPORTED")).schemas(dispatcher.schemas())
    assert "get_equipment" in advertised
    assert (
        "get_equipment_state" not in advertised
        and "prepare_equipment_state_update" not in advertised
    )
    assert "値を推測した自由な回答" not in result.answer
    assert "確認できません" in result.answer and "M-204" in result.answer
    assert any(row["code"] == "OUT_OF_SCOPE" for row in result.answer_sections["unavailable"])
    assert dispatcher.calls == 2 and not result.errors
    assert len(llm.planning_requests) == 1 and not llm.requests


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
    assert result.answer_sections["facts"][0]["predicate"] == "equipment.identity"


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


class ReviewedLLM(ScopedLLM):
    def __init__(self, review):
        super().__init__(
            ["UPSTREAM"], subjects=({"entity_type": "Equipment", "reference": "M-204"},)
        )
        self.review = review
        self.review_requests = []

    def complete(self, messages, *, schemas, deadline):
        if CHECK_TOOL in schemas:
            self.review_requests.append((messages, schemas, deadline))
            if isinstance(self.review, Exception):
                raise self.review
            return self.review
        return super().complete(messages, schemas=schemas, deadline=deadline)


class IdentityDispatcher(Dispatcher):
    def schemas(self):
        return {"search_equipment": {}, "trace_upstream_dependencies": {}}

    def run(self, context, tool, arguments, **kwargs):
        assert tool == "search_equipment"
        self.calls += 1
        return ReadResult(
            {
                "items": [
                    {
                        "equipment_id": str(UUID(int=1)),
                        "equipment_code": "M-204",
                        "equipment_name": "第1加工機",
                    }
                ],
                "next_cursor": None,
            },
            {"source": "POSTGRESQL"},
        )


@pytest.mark.parametrize("verdict", ["MISMATCH", "UNSUPPORTED", "UNCERTAIN"])
def test_question_scope_review_stops_unrelated_reads(verdict):
    dispatcher = IdentityDispatcher()
    llm = ReviewedLLM(call(CHECK_TOOL, {"verdict": verdict}))
    result = ReadAgent(dispatcher, llm).run(
        context(), request("M-204の交換部品はどこに保管されているか？")
    )
    assert dispatcher.calls == 2
    assert all(o.tool == "search_equipment" for o in result.observations)
    assert not result.needs_input
    assert {row["predicate"] for row in result.answer_sections["facts"]} == {"equipment.identity"}
    assert "第1加工機（M-204）のことですね。" in result.answer
    assert "M-204の交換部品はどこに保管されているか？" in result.answer
    assert "登録の有無や実際の状態を断定したものではありません" in result.answer
    assert "0件" not in result.answer
    assert any(
        row["code"] == "QUESTION_SCOPE_UNCONFIRMED" for row in result.answer_sections["unavailable"]
    )
    assert "交換部品" in llm.review_requests[0][0][1]["content"]
    assert "upstream_dependencies" in llm.review_requests[0][0][-1]["content"]
    assert llm.review_requests[0][2] == llm.planning_requests[0][2]


def test_question_scope_review_match_keeps_registered_facts():
    assert set(FIELD_MEANINGS) == set(FIELDS)
    dispatcher = Dispatcher()
    llm = ScopedLLM(["ATTRIBUTES"], call(), LLMReply("創作した文章", ()))
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 1 and result.answer_sections["facts"]
    assert "M-204" in result.answer and "創作した文章" not in result.answer


def test_question_scope_review_malformed_response_never_dispatches_domain_reads():
    dispatcher = IdentityDispatcher()
    llm = ReviewedLLM(call(CHECK_TOOL, {"verdict": "MATCH", "answer": "任意文"}))
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 2
    assert {row["predicate"] for row in result.answer_sections["facts"]} == {"equipment.identity"}
    assert "任意文" not in result.answer
    assert any(
        row["code"] == "QUESTION_SCOPE_UNCONFIRMED" for row in result.answer_sections["unavailable"]
    )


def test_question_scope_review_deadline_never_dispatches():
    dispatcher = Dispatcher()
    llm = ReviewedLLM(LLMError("AGENT_LIMIT_REACHED", "Read deadline reached"))
    with pytest.raises(ToolError) as error:
        ReadAgent(dispatcher, llm).run(context(), request())
    assert error.value.code == "AGENT_LIMIT_REACHED" and dispatcher.calls == 0


def test_identity_and_available_metadata_do_not_answer_another_property():
    scope = ReadScope(("ATTRIBUTES",), requested_fields=("active",))
    answer, sections = build_answer(
        (
            observed(
                data={
                    "equipment_name": "第1加工機",
                    "equipment_code": "E-42",
                    "active": True,
                    "equipment_type": "machine",
                    "version": 1,
                }
            ),
        ),
        scope=scope,
        question="第一加工機はまだ保証期間内か？",
    )
    assert "第1加工機（E-42）" in answer
    assert "machine" not in answer and "はい" not in answer and "version" not in answer
    assert {row["predicate"] for row in sections["facts"]} == {"equipment.identity"}
    assert any(row["code"] == "QUESTION_NOT_ANSWERED" for row in sections["unavailable"])
    assert sections["facts"][0]["references"] == ["observed-1"]


def test_explicit_registered_attribute_is_answered_without_dumping_other_fields():
    scope = ReadScope(("ATTRIBUTES",), requested_fields=("equipment_type",))
    answer, sections = build_answer(
        (
            observed(
                data={
                    "equipment_name": "検査装置",
                    "equipment_code": "E-99",
                    "equipment_type": "inspection",
                    "active": True,
                    "version": 7,
                }
            ),
        ),
        scope=scope,
        question="E-99の設備種別を教えてください",
    )
    assert "inspection" in answer and "はい" not in answer
    assert "QUESTION_NOT_ANSWERED" not in {row["code"] for row in sections["unavailable"]}
    assert all(row["references"] == ["observed-1"] for row in sections["facts"])
