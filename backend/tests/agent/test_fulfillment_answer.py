from copy import deepcopy

import pytest

from agent.test_read_agent import AdmittedPlanAgent, Dispatcher, ScriptedLLM, call, context, request
from linescope.agent.graph_answer import fulfillment_answer
from linescope.agent.read_agent import ReadObservation
from linescope.application.reads import ReadResult
from linescope.integrations.llm import LLMReply


def observation(tool, verdict, *, complete=True):
    data = {
        "analysis_scope": "DEPENDENCY_FULFILLMENT",
        "graph_sync_state": "CURRENT",
        "complete": complete,
        "determination": "INDETERMINATE"
        if not complete or verdict == "INDETERMINATE"
        else "DETERMINATE",
        "analysis_mode": "CURRENT",
        "not_evaluated": ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"],
    }
    if tool == "find_alternative_paths":
        data.update(
            target_results=[{"after": {"determination": verdict}}],
            alternatives=[{"availability": "UNKNOWN"}],
        )
        data["determination"] = "INDETERMINATE"
    else:
        data["findings"] = [{"determination": verdict}]
    return ReadObservation("g1", tool, ReadResult(data, {"paths": ["retained"]}))


@pytest.mark.parametrize(
    "tool,verdict,label",
    [
        ("find_alternative_paths", "ESTABLISHED", "成立1件"),
        ("find_alternative_paths", "NOT_ESTABLISHED", "不成立1件"),
        ("find_alternative_paths", "INDETERMINATE", "判定不明1件"),
        ("find_single_point_failure_candidates", "CANDIDATE", "候補1件"),
        ("find_single_point_failure_candidates", "NOT_CANDIDATE", "非候補1件"),
        ("find_single_point_failure_candidates", "INDETERMINATE", "判定不明1件"),
    ],
)
def test_structural_verdict_and_unevaluated_dimensions(tool, verdict, label):
    item = observation(tool, verdict)
    before = deepcopy(item.result)
    answer = fulfillment_answer([item], has_errors=True)
    assert label in answer
    assert "探索は完全" in answer and "未評価" in answer and "参照は失敗" in answer
    if tool == "find_alternative_paths":
        assert "不明1件" in answer and "全体判定は未確定" in answer
    assert item.result == before


@pytest.mark.parametrize("tool", ["find_alternative_paths", "find_single_point_failure_candidates"])
def test_partial_historical_result_does_not_claim_safe_or_restored(tool):
    item = observation(tool, "INDETERMINATE", complete=False)
    item.result.data["analysis_mode"] = "EXPLICIT_HISTORICAL"
    answer = fulfillment_answer([item])
    assert "探索は不完全" in answer and "全体判定は未確定" in answer
    assert "当時の状態の復元ではありません" in answer
    assert "未評価" in answer


def test_empty_spof_findings_are_not_no_spof():
    item = observation("find_single_point_failure_candidates", "NOT_CANDIDATE")
    item.result.data["findings"] = []
    assert "評価した組はなく、SPOFなしとは判断できません" in fulfillment_answer([item])


@pytest.mark.parametrize("case", ["multiple", "noncurrent", "invalid_verdict", "missing_scope"])
def test_unsupported_results_are_not_summarized(case):
    item = observation("find_alternative_paths", "ESTABLISHED")
    items = [item]
    if case == "multiple":
        items.append(item)
    elif case == "noncurrent":
        item.result.data["graph_sync_state"] = "LAGGING"
    elif case == "invalid_verdict":
        item.result.data["target_results"][0]["after"]["determination"] = "SAFE"
    else:
        item.result.data.pop("analysis_scope")
    assert fulfillment_answer(items) is None


@pytest.mark.parametrize(
    "tool,verdict",
    [
        ("find_alternative_paths", "ESTABLISHED"),
        ("find_single_point_failure_candidates", "NOT_CANDIDATE"),
    ],
)
def test_agent_replaces_unfounded_llm_claims_and_preserves_evidence(tool, verdict):
    item = observation(tool, verdict)

    class GraphDispatcher(Dispatcher):
        def schemas(self):
            return {tool: {"type": "object"}}

        def run(self, *args, **kwargs):
            return item.result

    result = AdmittedPlanAgent(
        GraphDispatcher(),
        ScriptedLLM(call(tool, {}), LLMReply("すべて安全で損失は0円。SPOFはありません。", ())),
    ).run(context(), request())
    assert "未評価" in result.answer and "0円" not in result.answer
    assert "すべて安全" not in result.answer and "SPOFはありません" not in result.answer
    assert result.observations[0].result == item.result


@pytest.mark.parametrize(
    "availability,label", [("AVAILABLE", "利用可能1件"), ("UNAVAILABLE", "利用不可1件")]
)
def test_known_replacement_availability_is_not_confused_with_unknown(availability, label):
    item = observation("find_alternative_paths", "ESTABLISHED")
    item.result.data["alternatives"][0]["availability"] = availability
    answer = fulfillment_answer([item])
    assert label in answer and "不明0件" in answer and "未評価" in answer
