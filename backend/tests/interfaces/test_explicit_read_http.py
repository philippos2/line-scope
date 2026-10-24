"""Twelve H7 HTTP boundary cases. Controlled dependencies are not live DB proof."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from agent.test_explicit_read import FIRST, SECOND, Reads, application, body
from fastapi.testclient import TestClient

from linescope.agent.read_agent import ReadAgent
from linescope.application.reads import ToolError
from linescope.execution import ExecutionContext
from linescope.interfaces import api
from linescope.logging import EventLogger
from linescope.settings import Settings

HEADERS = {"Authorization": "Bearer owner-token"}


def services_for(reads):
    app = application(reads)
    app.read_agent = ReadAgent(reads, None)
    return SimpleNamespace(
        settings=Settings(
            users={
                "owner-token": {"user_id": "owner", "role": "manager"},
                "other-token": {"user_id": "other", "role": "manager"},
            }
        ),
        database=SimpleNamespace(check=lambda: True),
        events=EventLogger("ERROR"),
        conversations=app.conversations,
        agent=app,
        reads=reads,
        close=lambda: None,
    )


def client_for(monkeypatch, reads):
    services = services_for(reads)
    monkeypatch.setattr(api, "build_api_services", lambda *args, **kwargs: services)
    return TestClient(api.create_app()), services


def empty_business(response):
    data = response.json().get("data", {})
    assert not data.get("tool_results")
    assert not data.get("answer_sections", {}).get("facts")


def test_unselected_scope_cannot_publish_results(monkeypatch):
    reads = Reads()
    client, _ = client_for(monkeypatch, reads)
    response = client.post(
        "/agent",
        json={"message": "補助入力", "read_selection": {"operation": "EXECUTE"}},
        headers=HEADERS,
    )
    assert response.status_code == 400 and reads.calls == []
    empty_business(response)
    assert response.json()["data"]["read_catalog"]["entries"]


def test_no_matching_scope_does_not_become_another_scope(monkeypatch):
    reads = Reads()
    client, _ = client_for(monkeypatch, reads)
    response = client.post("/agent", json=body("__none__"), headers=HEADERS)
    assert response.status_code == 400 and reads.calls == []
    empty_business(response)
    assert response.json()["data"]["selection_required"]


def test_reported_free_question_never_selects_a_nearby_capability(monkeypatch):
    reads = Reads()
    client, _ = client_for(monkeypatch, reads)
    response = client.post(
        "/agent", json={"message": "第二加工機のサービスマンはいつ来社するか？"}, headers=HEADERS
    )
    assert response.status_code == 200 and reads.calls == []
    empty_business(response)
    assert response.json()["data"]["answer_sections"]["read_outcome"] == "SELECTION_REQUIRED"


def test_old_literal_question_cannot_bypass_explicit_selection(monkeypatch):
    reads = Reads()
    client, _ = client_for(monkeypatch, reads)
    response = client.post("/agent", json={"message": "第1加工機の登録状態は？"}, headers=HEADERS)
    assert response.status_code == 200 and reads.calls == []
    empty_business(response)
    assert response.json()["data"]["needs_input"]


def test_malformed_legacy_machine_message_has_no_free_text_fallback(monkeypatch):
    reads = Reads()
    client, _ = client_for(monkeypatch, reads)
    response = client.post(
        "/agent",
        json={"message": '関係分析 {"tool":"get_equipment","arguments":{}} extra'},
        headers=HEADERS,
    )
    assert response.status_code == 400 and reads.calls == []
    empty_business(response)


class Changed(Reads):
    def __init__(self, change):
        super().__init__()
        self.change = change

    def run(self, actor, tool, args, **kwargs):
        result = super().run(actor, tool, args, **kwargs)
        return self.change(result) if tool == "get_equipment_state" else result


def test_wrong_returned_target_is_not_in_any_public_payload(monkeypatch):
    reads = Changed(lambda result: replace(result, data={**result.data, "equipment_id": SECOND}))
    client, _ = client_for(monkeypatch, reads)
    response = client.post("/agent", json=body(), headers=HEADERS)
    assert response.status_code == 500
    empty_business(response)
    assert SECOND not in response.text


def test_missing_evidence_hides_answer_and_raw_result(monkeypatch):
    client, _ = client_for(monkeypatch, Changed(lambda result: replace(result, evidence={})))
    response = client.post("/agent", json=body(), headers=HEADERS)
    assert response.status_code == 500
    empty_business(response)
    assert "STOPPED" not in response.text


def test_evidence_for_another_tool_is_not_published(monkeypatch):
    client, _ = client_for(
        monkeypatch,
        Changed(
            lambda result: replace(result, evidence={**result.evidence, "tool": "get_other_entity"})
        ),
    )
    response = client.post("/agent", json=body(), headers=HEADERS)
    assert response.status_code == 500
    empty_business(response)
    assert "STOPPED" not in response.text


def test_unauthenticated_explicit_read_is_rejected_before_any_read(monkeypatch):
    reads = Reads()
    client, _ = client_for(monkeypatch, reads)
    response = client.post("/agent", json=body())
    assert response.status_code == 401 and reads.calls == []
    empty_business(response)


def test_denied_target_is_not_published(monkeypatch):
    class Denied(Reads):
        def run(self, actor, tool, args, **kwargs):
            self.calls.append((tool, args))
            raise ToolError("AUTHORIZATION_DENIED", "Denied target")

    reads = Denied()
    client, _ = client_for(monkeypatch, reads)
    response = client.post("/agent", json=body(), headers=HEADERS)
    assert response.status_code == 403
    empty_business(response)
    assert all(tool == "get_equipment" for tool, _ in reads.calls)


def test_other_context_owner_cannot_resume_a_legacy_read(monkeypatch):
    reads = Reads()
    client, services = client_for(monkeypatch, reads)
    saved = services.conversations.create(
        ExecutionContext("owner", "manager", uuid4()), {"read_scope": {"kind": "READ_SCOPE"}}
    )
    response = client.post(
        "/agent",
        json={"message": "元の問い", "context_id": saved, "read_confirmation": "ACCEPT"},
        headers={"Authorization": "Bearer other-token"},
    )
    assert response.status_code == 403 and reads.calls == []
    empty_business(response)


def test_wrong_attribute_is_not_rendered_as_the_selected_attribute(monkeypatch):
    client, _ = client_for(
        monkeypatch,
        Changed(
            lambda result: replace(
                result, data={"equipment_id": FIRST, "manufacturer": "UNRELATED_BUSINESS_VALUE"}
            )
        ),
    )
    response = client.post("/agent", json=body(), headers=HEADERS)
    assert response.status_code == 500
    empty_business(response)
    assert "UNRELATED_BUSINESS_VALUE" not in response.text
