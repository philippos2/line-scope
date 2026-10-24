from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent.test_read_agent import AdmittedPlanAgent, Dispatcher, ScriptedLLM, call, context, request
from linescope.agent.graph_answer import downstream_answer
from linescope.agent.read_agent import ReadObservation
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
    item.result.data["representative_paths"] = [{"nodes": ["full-path-retained"]}]
    before = deepcopy(item.result)

    class GraphDispatcher(Dispatcher):
        def schemas(self):
            return {"trace_downstream_impact": {"type": "object"}}

        def run(self, *args, **kwargs):
            return item.result

    llm = ScriptedLLM(
        call("trace_downstream_impact", {}), LLMReply("すべて安全です。損失は0円です。", ())
    )
    result = AdmittedPlanAgent(GraphDispatcher(), llm).run(context(), request())
    assert "2件の依存到達候補" in result.answer
    assert "未評価" in result.answer
    assert "すべて安全" not in result.answer and "0円" not in result.answer
    assert result.observations[0].result == item.result
    import json

    payload = json.loads(llm.requests[-1][0][-1]["content"])
    assert "data" in payload and "evidence" in payload
    assert payload["data"]["representative_paths"] == before.data["representative_paths"]
    assert payload["evidence"] == before.evidence
    assert result.observations[0].result == before


def dependency_observation(tool, *, complete=True, empty=False):
    item = observation(complete=complete, empty=empty)
    data = deepcopy(item.result.data)
    if tool == "find_common_dependencies":
        data = {
            key: value
            for key, value in data.items()
            if key not in {"reached_nodes", "direct_nodes", "indirect_nodes"}
        }
        data.update(
            targets=[
                {"entity_type": "Product", "entity_id": "a"},
                {"entity_type": "Product", "entity_id": "b"},
            ],
            common_candidates=[] if empty else [{"entity_type": "Equipment", "entity_id": "e1"}],
        )
    return ReadObservation("d1", tool, ReadResult(data, item.result.evidence))


@pytest.mark.parametrize("tool", ["trace_upstream_dependencies", "find_common_dependencies"])
@pytest.mark.parametrize("complete,empty", [(True, False), (False, False), (False, True)])
def test_dependency_summary_preserves_scope_unknowns_and_input(tool, complete, empty):
    from linescope.agent.graph_answer import dependency_answer

    item = dependency_observation(tool, complete=complete, empty=empty)
    before = deepcopy(item.result)
    answer = dependency_answer([item], has_errors=True)
    assert "上流" in answer and ("0件" if empty else "1件") in answer
    assert ("確認済み" if complete else "探索は不完全") in answer
    assert "実際の停止影響・能力・安全性・経済影響は未評価" in answer
    assert "参照は失敗" in answer
    if tool == "find_common_dependencies":
        assert "原因やSPOFの確定判定ではありません" in answer
    assert "p1" not in answer and "e1" not in answer
    assert item.result == before


@pytest.mark.parametrize("case", ["noncurrent", "multiple"])
def test_dependency_summary_refuses_noncurrent_or_combined_analyses(case):
    from linescope.agent.graph_answer import dependency_answer

    item = dependency_observation("trace_upstream_dependencies")
    items = [item]
    if case == "noncurrent":
        item.result.data["graph_sync_state"] = "LAGGING"
    else:
        items.append(dependency_observation("find_common_dependencies"))
    assert dependency_answer(items) is None


@pytest.mark.parametrize("tool", ["trace_upstream_dependencies", "find_common_dependencies"])
def test_agent_dependency_summary_does_not_repeat_unsupported_claims(tool):
    item = dependency_observation(tool)

    class DependencyDispatcher(Dispatcher):
        def schemas(self):
            return {tool: {"type": "object"}}

        def run(self, *args, **kwargs):
            return item.result

    llm = ScriptedLLM(call(tool, {}), LLMReply("故障原因は確定。すべて安全で損失は0円です。", ()))
    result = AdmittedPlanAgent(DependencyDispatcher(), llm).run(context(), request())
    assert "上流" in result.answer and "未評価" in result.answer
    assert "故障原因は確定" not in result.answer and "0円" not in result.answer
    assert result.observations[0].result == item.result
