"""Single-domain prose cannot suppress a different part of an investigation."""

import pytest

from agent.test_read_agent import AdmittedPlanAgent, Dispatcher, ScriptedLLM, call, context, request
from linescope.application.reads import ReadResult
from linescope.integrations.llm import LLMReply


@pytest.mark.parametrize(
    "other_tool",
    [
        "get_equipment_state",
        "trace_downstream_impact",
        "get_economic_input",
        "search_maintenance_records",
    ],
)
def test_mixed_investigation_is_not_replaced_by_safety_search_summary(other_tool):
    class MixedDispatcher(Dispatcher):
        def schemas(self):
            return {name: {"type": "object"} for name in (other_tool, "search_safety_inputs")}

        def run(self, tool, *args, **kwargs):
            data = (
                {"state_code": "STOPPED", "version": 1}
                if tool == "get_equipment_state"
                else {"items": []}
            )
            return ReadResult(data, {"source": "POSTGRESQL"})

    prose = "取得した複数分野の結果は構造化結果を確認してください。安全入力は未登録です。"
    result = AdmittedPlanAgent(
        MixedDispatcher(),
        ScriptedLLM(call(other_tool), call("search_safety_inputs"), LLMReply(prose, ())),
    ).run(context(), request())
    assert result.answer != prose
    assert result.answer_sections["mode"] == "REGISTERED_RESULTS"
    references = {
        ref
        for row in result.answer_sections["facts"] + result.answer_sections["unavailable"]
        for ref in row["references"]
    }
    assert {row.tool_call_id for row in result.observations} <= references
    assert "安全判定は未取得" in result.answer
    assert len(result.observations) == 2 and len(result.trace) == 2
    assert not result.errors
    assert all(item.result.evidence == {"source": "POSTGRESQL"} for item in result.observations)
