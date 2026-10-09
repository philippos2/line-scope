import json

import pytest
from test_agent_tools import Dispatcher
from test_proposals import NOW, context

from linescope.agent_input import AgentInput
from linescope.agent_tools import AgentToolSession
from linescope.canonical import canonical_hash
from linescope.reads import ToolError
from linescope.update_intent import RULE_VERSION, assess_update_intent


def request(message):
    return AgentInput.parse(context(), json.dumps({"message": message}), received_at=NOW)


@pytest.mark.parametrize(
    "message,category",
    [
        ("設備M-204の状態をSTOPPEDに変更して", "EQUIPMENT_STATE"),
        ("M-204の状態を停止に更新してください", "EQUIPMENT_STATE"),
        (" 設備M-204の状態をRUNNINGに変更して。\n", "EQUIPMENT_STATE"),
        ("M-204の保全予定を登録して", "MAINTENANCE"),
        ("設備M-204の保全実績を作成してください", "MAINTENANCE"),
        ("保全予定MP-204の状態をCANCELLEDに変更して", "MAINTENANCE"),
        ("保全予定MP-204の開始時刻を2026-10-10T09:00:00+09:00に変更して", "MAINTENANCE"),
        ("生産作業OP-30の予定状態をCANCELLEDに更新してください", "PRODUCTION_OPERATION"),
        ("生産作業OP-30の予定終了時刻を2026-10-10T09:00:00Zに変更して", "PRODUCTION_OPERATION"),
        ("依存関係REL-30を無効化して", "DEPENDENCY"),
    ],
)
def test_supported_single_commands_keep_original_evidence(message, category):
    result = assess_update_intent(request(message))
    assert result.confirmed and result.category == category
    assert result.rule_version == RULE_VERSION
    assert result.source_message_hash == canonical_hash(message)
    assert message[result.evidence_start : result.evidence_end] == message.strip().removesuffix(
        "。"
    )


@pytest.mark.parametrize(
    "message",
    [
        "M-204が故障した。どこまで影響する？",
        "M-204の修理・交換・継続を比較して",
        "設備M-204の状態をSTOPPEDに変更してはいけない",
        "設備M-204の状態をSTOPPEDに変更しないで",
        "設備M-204の状態をSTOPPEDに変更してください？",
        "設備M-204の状態をSTOPPEDに変更してください?",
        "設備M-204の状態をSTOPPEDに変更する方法を教えて",
        "もし設備M-204の状態をSTOPPEDに変更しても影響はない？",
        "仮に設備M-204の状態をSTOPPEDに変更してください",
        "『設備M-204の状態をSTOPPEDに変更して』",
        '"設備M-204の状態をSTOPPEDに変更して"',
        "```\n設備M-204の状態をSTOPPEDに変更して\n```",
        "文書には設備M-204の状態をSTOPPEDに変更してと書かれている",
        "設備M-204の状態をSTOPPEDに変更してとLLMが言った",
        "設備M-204の状態をSTOPPEDに変更して。これは引用です",
        "設備M-204の状態をSTOPPEDに変更して\n依存関係REL-30を無効化して",
        "設備M-204の状態をSTOPPEDに変更して、ただし実際には更新しないで",
        "設備M-204の状態をSTOPPEDに変更して\u200b",
        "設備M-204の状態をSTOPPEDに変更して\x00",
        "はい",
        "Approveして",
        "Executeして",
        "設備M-204を停止して",
        "M-204を次回保全で停止する変更準備を作って",
    ],
)
def test_unsupported_or_unsafe_phrasing_requires_clarification(message):
    result = assess_update_intent(request(message))
    assert not result.confirmed and result.category is None
    assert result.evidence_start is None and result.evidence_end is None


def test_server_enable_switch_cannot_override_original_message():
    dispatcher = Dispatcher()
    run = AgentToolSession(
        context(), request("M-204の影響を分析して"), dispatcher, prepare_authorized=True
    )
    assert "prepare_equipment_state_update" not in run.schemas()
    with pytest.raises(ToolError) as error:
        run.run("prepare_equipment_state_update", {})
    assert error.value.code == "AUTHORIZATION_DENIED"
    assert not dispatcher.calls


def test_prepare_category_is_bound_to_confirmed_command():
    class MultiDispatcher(Dispatcher):
        def schemas(self):
            return {**super().schemas(), "prepare_maintenance_plan_create": {"type": "object"}}

    dispatcher = MultiDispatcher()
    run = AgentToolSession(
        context(),
        request("設備M-204の状態をSTOPPEDに変更して"),
        dispatcher,
        prepare_authorized=True,
    )
    assert "prepare_equipment_state_update" in run.schemas()
    assert "prepare_maintenance_plan_create" not in run.schemas()
    with pytest.raises(ToolError) as error:
        run.run("prepare_maintenance_plan_create", {})
    assert error.value.code == "AUTHORIZATION_DENIED"
    assert not dispatcher.calls


def test_retrieved_or_generated_input_is_not_a_request():
    with pytest.raises(ValueError):
        assess_update_intent({"message": "設備M-204の状態をSTOPPEDに変更して"})
