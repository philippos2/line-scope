"""Explicit nominal requests cannot be replaced by related record fields."""

import pytest
from application.test_proposals import context

from agent.test_read_agent import request
from agent.test_read_confirmation import Reads
from linescope.agent.read_agent import ReadAgent
from linescope.agent.read_scope import PLAN_TOOL
from linescope.agent.scope_check import CHECK_TOOL
from linescope.application.reads import ReadResult
from linescope.integrations.llm import LLMReply, ToolCall


class AgreeingModel:
    def complete(self, messages, *, schemas, deadline):
        if CHECK_TOOL in schemas:
            # Deliberately reproduce correlated false agreement, not a helpful rejection.
            return LLMReply("", (ToolCall("review", CHECK_TOOL, {"verdict": "MATCH"}),))
        assert PLAN_TOOL in schemas
        return LLMReply(
            "",
            (
                ToolCall(
                    "plan",
                    PLAN_TOOL,
                    {
                        "topics": ["MAINTENANCE"],
                        "subjects": [{"entity_type": "Equipment", "reference": "E-7"}],
                        "requested_fields": ["maintenance_records"],
                        "source_spans": [{"text": messages[-1]["content"]}],
                    },
                ),
            ),
        )


@pytest.mark.parametrize(
    "question,attribute",
    [
        ("E-7の故障原因は何か？", "故障原因"),
        ("E-7の保証期限を教えて", "保証期限"),
        ("E-7の製造元は何ですか？", "製造元"),
        ("E-7の保全記録にない原因は何か？", "保全記録にない原因"),
    ],
)
def test_model_agreement_cannot_substitute_an_explicit_unbound_attribute(question, attribute):
    reads = Reads()
    result = ReadAgent(reads, AgreeingModel()).run(context(), request(question))
    assert result.read_clarification is None and result.pending_read is None
    assert result.answer_sections["read_outcome"] == "UNVERIFIABLE"
    assert result.answer_sections["verification"]["stage"] == "REQUEST_FIELD"
    assert {f["predicate"] for f in result.answer_sections["facts"]} == {"equipment.identity"}
    assert (
        f"「{attribute}」は、現在LineScopeで参照できる情報からは確認できません。" in result.answer
    )
    assert "試験設備（E-7）" in result.answer
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


class RecordReads(Reads):
    def schemas(self):
        return {
            **super().schemas(),
            "search_maintenance_records": {},
            "search_maintenance_plans": {},
        }

    def run(self, context, tool, arguments, **kwargs):
        if tool in {"search_maintenance_records", "search_maintenance_plans"}:
            self.calls.append((tool, arguments))
            return ReadResult({"items": [], "next_cursor": None}, {})
        return super().run(context, tool, arguments, **kwargs)


@pytest.mark.parametrize(
    "question,confirmation",
    [("E-7、調子はどう？", True), ("E-7の保全記録は？", False)],
)
def test_ambiguous_predicate_and_registered_record_request_are_not_rejected(question, confirmation):
    reads = RecordReads()
    result = ReadAgent(reads, AgreeingModel()).run(context(), request(question))
    if confirmation:
        assert result.read_clarification["status"] == "PENDING"
        assert all(tool == "search_equipment" for tool, _ in reads.calls)
    else:
        assert result.read_clarification is None
        assert result.answer_sections["read_outcome"] == "AUTO"
        assert any(tool == "search_maintenance_records" for tool, _ in reads.calls)
        assert "0件" in result.answer


def test_saved_model_agreement_cannot_bypass_attribute_binding_on_accept():
    from dataclasses import replace

    from linescope.agent.read_confirmation import confirmed_read, original_hash

    reads = RecordReads()
    reader = ReadAgent(reads, AgreeingModel())
    first = reader.run(context(), request("E-7、調子はどう？"))
    # Simulate a server-owned pending entry issued by the former policy.
    original = request("E-7の保証期限は何か？")
    saved = {**first.pending_read, "hash": original_hash(original)}
    result = confirmed_read(reader, context(), replace(original, read_confirmation="ACCEPT"), saved)
    assert result.read_clarification is None and result.pending_read is None
    assert result.answer_sections["read_outcome"] == "UNVERIFIABLE"
    assert all(tool == "search_equipment" for tool, _ in reads.calls)
    assert "保証期限" in result.answer
