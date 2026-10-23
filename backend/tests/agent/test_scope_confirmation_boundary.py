"""Public question gate: a rejected meaning is not a clarification candidate."""

import pytest
from application.test_proposals import context

from agent.test_read_agent import request
from agent.test_read_confirmation import Reads
from linescope.agent.read_agent import ReadAgent
from linescope.agent.read_scope import PLAN_TOOL
from linescope.agent.scope_check import CHECK_TOOL
from linescope.integrations.llm import LLMReply, ToolCall


class MeaningReview:
    def __init__(self, verdict):
        self.verdict = verdict

    def complete(self, messages, *, schemas, deadline):
        if CHECK_TOOL in schemas:
            return LLMReply("", (ToolCall("review", CHECK_TOOL, {"verdict": self.verdict}),))
        assert PLAN_TOOL in schemas
        return LLMReply(
            "",
            (
                ToolCall(
                    "plan",
                    PLAN_TOOL,
                    {
                        "topics": ["STATE"],
                        "subjects": [{"entity_type": "Equipment", "reference": "E-7"}],
                        "requested_fields": ["registered_state"],
                        "source_spans": [{"text": messages[-1]["content"]}],
                    },
                ),
            ),
        )


@pytest.mark.parametrize(
    "verdict,question,confirmation,requested_information",
    [
        ("MISMATCH", "E-7の契約はまだ有効か？", False, "契約"),
        ("MISMATCH", "E-7が止まった理由を教えて", False, "理由"),
        ("UNSUPPORTED", "E-7の予備品の置き場所は？", False, "予備品の置き場所"),
        ("UNCERTAIN", "E-7、調子はどう？", True, None),
        ("MATCH", "E-7、動いている？", True, None),
    ],
)
def test_only_plausible_read_meaning_can_be_offered_for_confirmation(
    verdict, question, confirmation, requested_information
):
    reads = Reads()
    result = ReadAgent(reads, MeaningReview(verdict)).run(context(), request(question))
    assert all(tool == "search_equipment" for tool, _ in reads.calls)
    if confirmation:
        assert result.read_clarification["status"] == "PENDING"
        assert result.read_clarification["original_question"] == question
    else:
        assert result.read_clarification is None
        assert result.pending_read is None
        assert result.answer_sections["unavailable"]
        assert result.answer_sections["read_outcome"] in {"UNSUPPORTED", "UNVERIFIABLE"}
        assert {f["predicate"] for f in result.answer_sections["facts"]} == {"equipment.identity"}
        assert requested_information in result.answer


def test_rejected_saved_scope_cannot_be_executed_by_accepting_it():
    from dataclasses import replace

    from linescope.agent.read_confirmation import confirmed_read

    reads = Reads()
    reader = ReadAgent(reads, MeaningReview("MATCH"))
    original = request("E-7、動いている？")
    first = reader.run(context(), original)
    saved = dict(first.pending_read)
    saved["scope"] = replace(saved["scope"], scope_issue="MISMATCH")
    result = confirmed_read(reader, context(), replace(original, read_confirmation="ACCEPT"), saved)
    assert result.read_clarification is None and result.pending_read is None
    assert result.answer_sections["read_outcome"] == "UNVERIFIABLE"
    assert all(tool == "search_equipment" for tool, _ in reads.calls)
