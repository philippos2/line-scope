"""Question-boundary regressions: identity and answerability are independent.

Controlled model responses test public ReadAgent behavior, not model accuracy.
Four representatives avoid a topics x fields x target Cartesian product.
"""

import pytest
from application.test_proposals import context

from agent.test_read_agent import request
from agent.test_read_confirmation import Reads
from linescope.agent.read_agent import ReadAgent
from linescope.agent.read_scope import PLAN_TOOL
from linescope.integrations.llm import LLMReply, ToolCall


class FailedPlan:
    def __init__(self, case):
        self.case = case

    def complete(self, messages, *, schemas, deadline):
        assert set(schemas) == {PLAN_TOOL}
        arguments = {
            "topics": ["UNSUPPORTED"],
            "subjects": [{"entity_type": "Equipment", "reference": "E-7"}],
            "requested_fields": ["contract_expiry"],
            "source_spans": [{"text": messages[-1]["content"]}],
        }
        if self.case == "invalid_topic":
            arguments["topics"] = ["not_a_capability"]
        elif self.case == "invalid_fields":
            arguments["requested_fields"] = None
        elif self.case == "invented_target":
            arguments["subjects"][0]["reference"] = "E-999"
        return LLMReply("", (ToolCall("plan", PLAN_TOOL, arguments),))


@pytest.mark.parametrize(
    "case,question,identity_expected",
    [
        ("invalid_topic", "E-7の部材はどこに置いてある？", True),
        ("invalid_fields", "E-7の担当者はいつ到着する？", True),
        ("unsupported", "E-7の契約はいつ切れる？", True),
        ("invented_target", "E-7の取得価格はいくら？", False),
    ],
)
def test_question_failure_retains_only_independently_verified_identity(
    case, question, identity_expected
):
    reads = Reads()
    result = ReadAgent(reads, FailedPlan(case)).run(context(), request(question))
    sections = result.answer_sections
    facts = sections["facts"]
    assert sections["read_outcome"] in {"UNVERIFIABLE", "UNSUPPORTED"}
    assert sections["unavailable"] and question in result.answer
    assert result.read_clarification is None
    assert all(tool == "search_equipment" for tool, _ in reads.calls)
    assert all(fact["predicate"] == "equipment.identity" for fact in facts)
    if identity_expected:
        assert len(facts) == 1
        assert "試験設備（E-7）" in facts[0]["text"]
        assert facts[0]["references"]
        assert reads.calls
    else:
        assert facts == [] and reads.calls == []
