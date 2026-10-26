"""26 approved cases: nine views, eight refusals, nine failure/state boundaries."""

import io
import re
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agent.test_fulfillment_answer import observation
from fastapi.testclient import TestClient

from linescope.agent.agent_input import ConversationStore
from linescope.agent.registered_question_read import RegisteredQuestionReads
from linescope.application.agent_service import AgentApplication
from linescope.application.demo_questions import DemoQuestions
from linescope.application.reads import ReadResult, ToolError
from linescope.domain.reference_normalization import code_key, lexical_key, name_reference_pattern
from linescope.execution import ExecutionContext
from linescope.interfaces import api
from linescope.logging import EventLogger
from linescope.settings import Settings

FIRST, SECOND, PRODUCT = (str(UUID(int=i)) for i in (21, 22, 30))
HEADERS = {"Authorization": "Bearer token"}
NOW = "2026-10-26T00:00:00Z"


class Reads:
    def __init__(self, mode="normal"):
        self.mode, self.calls = mode, []

    def schemas(self):
        return {
            name: {}
            for name in [
                "search_equipment",
                "get_equipment",
                "get_equipment_state",
                "search_maintenance_records",
                "search_maintenance_plans",
                "trace_upstream_dependencies",
                "trace_downstream_impact",
                "find_alternative_paths",
                "get_product",
            ]
        }

    def run(self, context, tool, args, **kwargs):
        self.calls.append((tool, args))
        if self.mode == "authorization":
            raise ToolError("AUTHORIZATION_DENIED", "Controlled denial")
        if self.mode == "unavailable" and tool == "get_equipment_state":
            raise ToolError("DEPENDENCY_UNAVAILABLE", "Controlled read failure")
        equip = {
            "equipment_id": FIRST,
            "equipment_name": "第1加工機",
            "equipment_code": "M-204",
            "equipment_type": "machine",
            "active": True,
            "version": 1,
        }
        if tool == "search_equipment":
            rows = [
                equip,
                {
                    **equip,
                    "equipment_id": SECOND,
                    "equipment_name": "第2加工機",
                    "equipment_code": "M-208",
                },
            ]
            ref = args.get("filter", {}).get("reference")
            if ref:
                rows = [
                    r
                    for r in rows
                    if code_key(ref) == code_key(r["equipment_code"])
                    or re.search(name_reference_pattern(ref), lexical_key(r["equipment_name"]))
                ]
            data = {"items": rows, "next_cursor": None}
        elif tool == "get_equipment":
            data = dict(equip)
            if args["equipment_id"] == SECOND:
                data.update(equipment_id=SECOND, equipment_name="第2加工機", equipment_code="M-208")
            if self.mode == "attribute":
                data.pop("equipment_type")
        elif tool == "get_equipment_state":
            data = {
                "equipment_id": SECOND if self.mode == "target" else args["equipment_id"],
                "state_code": "STOPPED",
                "version": 1,
            }
        elif tool.startswith("search_maintenance"):
            data = {"items": [], "next_cursor": None}
        elif tool.startswith("trace_"):
            nodes = [{"entity_type": "Product", "entity_id": PRODUCT}]
            data = {
                "target": args["target"],
                "analysis_scope": "DEPENDENCY_REACHABILITY",
                "graph_sync_state": "CURRENT",
                "complete": True,
                "reached_nodes": nodes,
                "direct_nodes": nodes,
                "indirect_nodes": [],
                "not_evaluated": ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"],
            }
        elif tool == "get_product":
            data = {"product_id": PRODUCT, "product_name": "製品A", "product_code": "P-100"}
        elif tool == "find_alternative_paths":
            data = observation(tool, "ESTABLISHED").result.data
        else:
            raise AssertionError(tool)
        evidence = {"tool": tool, "source": "CONTROLLED", "observed_at": NOW}
        if tool == "get_equipment_state" and self.mode == "evidence":
            evidence = {}
        if tool == "get_equipment_state" and self.mode == "evidence_mismatch":
            evidence["tool"] = "get_equipment"
        return ReadResult(data, evidence)


def services(mode="normal"):
    reads, clock = Reads(mode), [0]
    store = ConversationStore(clock=lambda: clock[0])
    questions = DemoQuestions(RegisteredQuestionReads(reads))
    agent = AgentApplication(
        proposals=SimpleNamespace(),
        conversations=store,
        equipment=None,
        maintenance=None,
        production=None,
        read_agent=None,
        questions=questions,
    )
    result = SimpleNamespace(
        settings=Settings(
            users={
                "token": {"user_id": "owner", "role": "manager"},
                "other": {"user_id": "other", "role": "manager"},
            }
        ),
        database=SimpleNamespace(check=lambda: True),
        events=EventLogger("ERROR", io.StringIO()),
        conversations=store,
        agent=agent,
        reads=reads,
        close=lambda: None,
    )
    return result, clock


def client(monkeypatch, mode="normal"):
    result, clock = services(mode)
    monkeypatch.setattr(api, "build_api_services", lambda *a, **k: result)
    return TestClient(api.create_app()), result, clock


@pytest.mark.parametrize(
    "key,question",
    [
        ("registered_state", "m204の登録状態は？"),
        ("downstream_reachability", "M204停止の影響範囲はどこまでか？"),
        ("upstream_dependencies", "第一加工機は何に依存しているか？"),
        ("alternative_candidates", "第１加工機の代替候補は？"),
        ("maintenance_records", "第一加工機の保全記録は？"),
        ("maintenance_plans", "M-204のメンテナンス予定は？"),
        ("equipment_name", "m204の設備名は？"),
        ("equipment_code", "第一加工機の設備コードは？"),
        ("equipment_type", "M204の設備種別は？"),
    ],
)
def test_demo_direct_registered_read(monkeypatch, key, question):
    api_client, svc, _ = client(monkeypatch)
    with api_client:
        result = api_client.post("/agent", json={"message": question}, headers=HEADERS)
    assert result.status_code == 200, result.text
    body = result.json()
    data = body["data"]
    assert data["answer_sections"]["selected_field"] == key
    assert data["answer_sections"]["read_outcome"] == "ANSWERED"
    assert "第1加工機" in body["answer"] and "M-204" in body["answer"]
    assert data["answer_sections"]["facts"] and body["evidence"]["tool_results"]
    assert all(not tool.startswith("prepare") for tool, _ in svc.reads.calls)
    for row in data["tool_results"]:
        if row["tool"] == "get_equipment":
            assert not {"active", "version"} & row["data"].keys()
    if key == "registered_state":
        assert "登録上" in body["answer"] and "実稼働状態を確認したものではなく" in body["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "第二加工機のサービスマンはいつ来社するか？",
        "第2加工機の保証書は、月の裏側の金庫に入っていますか？",
        "m204の製造メーカーの顧客対応電話番号は何か？",
        "M-204の状態とメーカー電話番号は？",
        "M-204の登録状態と保全記録は？",
        "M-204は動いていないか？",
        "M-204の保証の登録状態は？",
        "M-204の気分はいかが？",
    ],
)
def test_demo_refusals_do_not_answer_another_question(monkeypatch, question):
    api_client, svc, _ = client(monkeypatch)
    with api_client:
        result = api_client.post("/agent", json={"message": question}, headers=HEADERS)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["data"]["answer_sections"]["read_outcome"] == "UNSUPPORTED"
    assert "確認できましたが" in body["answer"] and "例えば" in body["answer"]
    assert {tool for tool, _ in svc.reads.calls} == {"search_equipment"}
    assert "STOPPED" not in result.text and "machine" not in result.text


@pytest.mark.parametrize(
    "mode",
    [
        "empty",
        "unavailable",
        "evidence",
        "evidence_mismatch",
        "target",
        "attribute",
        "authorization",
        "owner",
        "ttl",
    ],
)
def test_demo_state_security_and_evidence(monkeypatch, mode):
    api_client, svc, clock = client(monkeypatch, mode)
    message = (
        "M204の保全記録は？"
        if mode == "empty"
        else "M204の設備種別は？"
        if mode == "attribute"
        else "M204の登録状態は？"
    )
    body = {"message": message}
    headers = HEADERS
    if mode in {"owner", "ttl"}:
        actor = ExecutionContext("owner", "manager", uuid4())
        identity = svc.conversations.create(
            actor,
            {"question": {"original": message, "key": "registered_state", "candidates": [FIRST]}},
        )
        body = {"message": "M204", "context_id": identity}
        if mode == "owner":
            headers = {"Authorization": "Bearer other"}
        else:
            clock[0] = 1800
    with api_client:
        result = api_client.post("/agent", json=body, headers=headers)
    if mode == "empty":
        assert result.status_code == 200
        assert "登録されていません" in result.json()["answer"]
        assert "未実施という意味ではありません" in result.json()["answer"]
    else:
        assert result.status_code in {403, 409, 500, 503}, result.text
        data = result.json().get("data", {})
        assert not data.get("tool_results") and not data.get("answer_sections", {}).get("facts")
        assert "STOPPED" not in result.text
        if mode in {"owner", "ttl"}:
            assert svc.reads.calls == []
