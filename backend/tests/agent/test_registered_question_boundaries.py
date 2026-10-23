"""Seven approved boundary cases, not an exhaustive natural-language evaluator."""

from dataclasses import replace

from application.test_proposals import context

from agent.test_explicit_attribute_boundary import AgreeingModel, RecordReads
from agent.test_read_agent import request
from agent.test_read_confirmation import Hint, Reads
from linescope.agent.read_agent import ReadAgent
from linescope.agent.read_catalog import BUSINESS_FIELDS, SHAPES
from linescope.agent.read_scope import PLAN_TOOL
from linescope.agent.scope_check import CHECK_TOOL
from linescope.application.reads import ReadResult
from linescope.integrations.llm import LLMReply, ToolCall


class NominalModel:
    def __init__(self, references, fields=("registered_state",)):
        self.references, self.fields = references, fields

    def complete(self, messages, *, schemas, deadline):
        if CHECK_TOOL in schemas:
            return LLMReply("", (ToolCall("review", CHECK_TOOL, {"verdict": "MATCH"}),))
        return LLMReply(
            "",
            (
                ToolCall(
                    "plan",
                    PLAN_TOOL,
                    {
                        "topics": list(
                            dict.fromkeys(BUSINESS_FIELDS[field] for field in self.fields)
                        ),
                        "subjects": [
                            {"entity_type": "Equipment", "reference": ref}
                            for ref in self.references
                        ],
                        "requested_fields": list(self.fields),
                        "source_spans": [{"text": messages[-1]["content"]}],
                    },
                ),
            ),
        )


class TwoReads(Reads):
    def run(self, context, tool, arguments, **kwargs):
        if tool == "search_equipment" and next(iter(arguments["filter"].values())) == "E-8":
            self.calls.append((tool, arguments))
            return ReadResult(
                {
                    "items": [
                        {
                            "equipment_id": "00000000-0000-0000-0000-000000000008",
                            "equipment_name": "対照設備",
                            "equipment_code": "E-8",
                        }
                    ],
                    "next_cursor": None,
                },
                {},
            )
        return super().run(context, tool, arguments, **kwargs)


def test_nominal_membership_cannot_be_replaced_by_registered_state():
    reads = Reads()
    result = ReadAgent(reads, NominalModel(["E-7"])).run(
        context(), request("E-7はまだ契約範囲内か？")
    )
    assert result.answer_sections["read_outcome"] == "UNSUPPORTED"
    assert result.read_clarification is None
    assert "契約範囲" in result.answer
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


def test_multiple_subjects_do_not_license_every_registered_field():
    reads = TwoReads()
    result = ReadAgent(reads, NominalModel(["E-7", "E-8"], tuple(BUSINESS_FIELDS)[:16])).run(
        context(), request("E-7とE-8の製造元は同じか？")
    )
    assert result.answer_sections["read_outcome"] == "UNSUPPORTED"
    assert result.read_clarification is None
    assert "試験設備（E-7）" in result.answer and "対照設備（E-8）" in result.answer
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


class EventReads(RecordReads):
    def run(self, context, tool, arguments, **kwargs):
        if tool == "search_maintenance_records":
            self.calls.append((tool, arguments))
            return ReadResult(
                {
                    "items": [
                        {
                            "record_code": "EVENT-A",
                            "performed_at": "2025-03-01T01:00:00Z",
                            "version": 1,
                        },
                        {
                            "record_code": "EVENT-B",
                            "performed_at": "2025-04-01T02:00:00Z",
                            "version": 1,
                        },
                    ],
                    "next_cursor": None,
                },
                {},
            )
        return super().run(context, tool, arguments, **kwargs)


def test_registered_event_time_uses_existing_record_read():
    reads = EventReads()
    result = ReadAgent(reads, AgreeingModel()).run(
        context(), request("E-7が最後に保全されたのはいつか？")
    )
    assert len(SHAPES) == 7
    assert result.answer_sections["read_outcome"] == "AUTO"
    assert result.read_clarification is None
    assert "実施日時の最大値：2025/04/01 11:00:00（日本時間）" in result.answer
    assert "実際の全保全作業を網羅した日時とは限りません" in result.answer
    assert any(
        fact["predicate"] == "maintenance_record.max_registered_date" and fact["references"]
        for fact in result.answer_sections["facts"]
    )
    assert any(tool == "search_maintenance_records" for tool, _ in reads.calls)


def test_unregistered_event_does_not_borrow_record_time():
    reads = RecordReads()
    result = ReadAgent(reads, AgreeingModel()).run(
        context(), request("E-7が最後に輸送されたのはいつか？")
    )
    assert result.answer_sections["read_outcome"] == "UNSUPPORTED"
    assert result.read_clarification is None
    assert "輸送" in result.answer
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


def test_missing_selection_requires_context_without_literal_name_lookup():
    reads = Reads()
    result = ReadAgent(reads, NominalModel(["その機械"])).run(
        context(), request("その機械の登録状態は？")
    )
    assert result.answer_sections["read_outcome"] == "TARGET_REQUIRED"
    assert result.needs_input and not reads.calls
    assert "設備名・コード" in result.answer


def test_selected_context_supplies_deictic_reference():
    reads = Reads()
    result = ReadAgent(reads, Hint()).run(
        context(role="manager"),
        replace(request(), message="調査対象の設備コードはE-7です。\nその機械の登録状態は？"),
    )
    assert result.answer_sections["read_outcome"] == "AUTO"
    assert "STOPPED" in str(result.answer_sections) or "停止" in result.answer
    assert any(tool == "get_equipment_state" for tool, _ in reads.calls)


def test_completed_empty_target_lookup_is_not_retrieval_failure():
    reads = Reads()
    result = ReadAgent(reads, Hint()).run(context(), request("E-9の登録状態は？"))
    assert result.answer_sections["read_outcome"] == "TARGET_NOT_FOUND"
    assert not any(item["code"] == "READ_FAILED" for item in result.answer_sections["unavailable"])
    assert result.errors and all(error["code"] == "TARGET_NOT_FOUND" for error in result.errors)
    assert any(tool == "search_equipment" for tool, _ in reads.calls)
