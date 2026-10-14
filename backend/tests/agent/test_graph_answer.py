from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent.test_read_agent import Dispatcher, ScriptedLLM, call, context, request
from linescope.agent.graph_answer import downstream_answer
from linescope.agent.read_agent import ReadAgent, ReadObservation
from linescope.application.reads import ReadResult
from linescope.integrations.llm import LLMReply


def observation(*, complete=True, empty=False):
    nodes = (
        []
        if empty
        else [
            {"entity_type": "Process", "entity_id": "p1"},
            {"entity_type": "Product", "entity_id": "p2"},
        ]
    )
    return ReadObservation(
        "g1",
        "trace_downstream_impact",
        ReadResult(
            {
                "analysis_scope": "DEPENDENCY_REACHABILITY",
                "graph_sync_state": "CURRENT",
                "not_evaluated": ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"],
                "complete": complete,
                "reached_nodes": nodes,
                "direct_nodes": nodes[:1],
                "indirect_nodes": nodes[1:],
            },
            {"representative_paths": ["retained"]},
        ),
    )


@pytest.mark.parametrize("complete,empty", [(True, False), (False, False), (False, True)])
def test_counts_completeness_and_unevaluated_dimensions(complete, empty):
    item = observation(complete=complete, empty=empty)
    before = deepcopy(item.result)
    answer = downstream_answer([item], has_errors=True)
    assert ("0件" if empty else "工程1件") in answer
    assert ("確認済み" if complete else "探索は不完全") in answer
    assert "実際の停止影響・能力・安全性・経済影響は未評価" in answer
    assert "参照は失敗" in answer
    assert "p1" not in answer and "p2" not in answer
    assert item.result == before


@pytest.mark.parametrize("case", ["upstream", "multiple", "inconsistent"])
def test_unsupported_analyses_are_not_mislabelled_as_downstream(case):
    item = observation()
    items = [item]
    if case == "upstream":
        items = [SimpleNamespace(tool="trace_upstream_dependencies", result=item.result)]
    elif case == "multiple":
        items.append(item)
    else:
        item.result.data["indirect_nodes"] = []
    assert downstream_answer(items) is None


def test_agent_does_not_repeat_unsupported_llm_claims_in_downstream_summary():
    item = observation()

    class GraphDispatcher(Dispatcher):
        def schemas(self):
            return {"trace_downstream_impact": {"type": "object"}}

        def run(self, *args, **kwargs):
            return item.result

    llm = ScriptedLLM(
        call("trace_downstream_impact", {}), LLMReply("すべて安全です。損失は0円です。", ())
    )
    result = ReadAgent(GraphDispatcher(), llm).run(context(), request())
    assert "2件の依存到達候補" in result.answer
    assert "未評価" in result.answer
    assert "すべて安全" not in result.answer and "0円" not in result.answer
    assert result.observations[0].result == item.result
