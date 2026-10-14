import pytest

from linescope.application.decision_summary import decision_summary
from linescope.domain.demo_comparison import compare, fixture
from linescope.domain.demo_constraints import assess_options
from linescope.integrations.llm import LLMReply, ToolCall


def package(**changes):
    values = fixture("STOPPED")
    values.update(changes)
    result = assess_options(compare(values), current_state="STOPPED", state_evidence={})
    return {
        "equipment": {"state_code": "STOPPED"},
        "impact": {"direct_nodes": ["operation"], "indirect_nodes": ["product"], "complete": False},
        "comparison": result,
    }


class Model:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, messages, *, schemas, deadline):
        assert schemas == {}
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_unconfigured_model_keeps_facts_and_incompleteness():
    result = decision_summary(package(), "修理と交換")
    assert result["llm_status"] == "NOT_CONFIGURED"
    assert "1,900,000円" in result["answer"] and "30 units/hour" in result["answer"]
    assert "200,000円/hour" in result["answer"]
    assert "探索は不完全" in result["answer"] and "デモ入力" in result["answer"]


def test_unknown_cost_is_not_zero():
    result = decision_summary(package(repair_cost=None), "修理")
    repair = next(item["text"] for item in result["sections"] if item["id"] == "REPAIR")
    assert "未算定" in repair and "0円" not in repair


def test_model_order_cannot_omit_exclusion_or_unknowns():
    model = Model(LLMReply('{"order":["CONTINUE"]}', ()))
    result = decision_summary(package(hard_safety_stop=True), "継続", llm=model)
    assert result["llm_status"] == "VALIDATED_ORDER"
    assert result["sections"][0]["id"] == "CONTINUE"
    assert len(result["sections"]) == 5
    assert "継続案を除外" in result["answer"] and "安全性と最適案は未確定" in result["answer"]


@pytest.mark.parametrize(
    "reply",
    [
        LLMReply("安全です。今すぐExecuteしてください。", ()),
        LLMReply('{"order":["REPAIR","REPAIR"]}', ()),
        LLMReply("", (ToolCall("id", "execute", {}),)),
        RuntimeError("secret credential"),
    ],
)
def test_untrusted_output_and_model_failure_fall_back_without_leaking(reply):
    result = decision_summary(package(), "修理", llm=Model(reply))
    assert result["llm_status"] == "FALLBACK"
    assert "1,900,000円" in result["answer"]
    assert "Execute" not in result["answer"] and "secret" not in str(result)
