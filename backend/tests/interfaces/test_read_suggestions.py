"""Eight approved suggestion-boundary cases; no real model or business writes."""

import pytest
from agent.test_explicit_read import Reads, body
from fastapi.testclient import TestClient

from interfaces.test_explicit_read_http import HEADERS, empty_business, services_for
from linescope.agent.read_scope import PLAN_TOOL
from linescope.integrations.llm import LLMError, LLMReply, ToolCall
from linescope.interfaces import api

QUESTION = "検証装置の登録状態は？"


class Model:
    def __init__(self, mode):
        self.mode, self.calls = mode, []

    def complete(self, messages, *, schemas, deadline):
        self.calls.append(tuple(schemas))
        if self.mode in {"failure", "deadline"}:
            raise LLMError(
                "AGENT_LIMIT_REACHED" if self.mode == "deadline" else "DEPENDENCY_UNAVAILABLE",
                "Controlled provider failure",
            )
        if self.mode == "malformed":
            return LLMReply("架空の業務値を公開しない", ())
        if PLAN_TOOL in schemas:
            fields = {
                "unsupported": ["unregistered_field"],
                "mixed": ["registered_state", "unregistered_field"],
            }.get(self.mode, ["registered_state"])
            return LLMReply(
                "",
                (
                    ToolCall(
                        "p",
                        PLAN_TOOL,
                        {
                            "topics": ["STATE"],
                            "subjects": [{"entity_type": "Equipment", "reference": "検証装置"}],
                            "requested_fields": fields,
                            "source_spans": [{"text": QUESTION}],
                        },
                    ),
                ),
            )
        tool = next(iter(schemas))
        return LLMReply("", (ToolCall("c", tool, {"verdict": "MATCH"}),))


@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "unsupported",
        "mixed",
        "unconfigured",
        "failure",
        "deadline",
        "malformed",
        "typed",
    ],
)
def test_suggestions_never_execute_or_publish_unconfirmed_business_data(monkeypatch, mode):
    reads = Reads()
    services = services_for(reads)
    model = Model(mode)
    services.agent.read_agent.llm = None if mode == "unconfigured" else model
    monkeypatch.setattr(api, "build_api_services", lambda *args, **kwargs: services)
    with TestClient(api.create_app()) as client:
        if mode == "typed":
            for value in (
                {"message": QUESTION, "read_selection": {"operation": "CATALOG"}},
                body(),
            ):
                response = client.post("/agent", json=value, headers=HEADERS)
                assert response.status_code == 200
            assert model.calls == []
            assert response.json()["data"]["answer_sections"]["facts"]
            return
        response = client.post("/agent", json={"message": QUESTION}, headers=HEADERS)
        assert response.status_code == 200 and reads.calls == []
        empty_business(response)
        data = response.json()["data"]
        proposal = data["read_suggestions"]
        assert data["read_catalog"]["entries"]
        assert data["answer_sections"]["read_outcome"] == "SELECTION_REQUIRED"
        assert response.json()["context_id"] is None
        assert proposal["question"] == QUESTION
        assert all(set(c) == {"key"} for c in proposal["candidates"])
        if mode == "valid":
            assert proposal["status"] == "PROPOSED"
            assert proposal["candidates"] == [{"key": "registered_state"}]
            assert proposal["subject_references"] == [
                {"entity_type": "Equipment", "reference": "検証装置"}
            ]
        else:
            assert proposal["candidates"] == [] and proposal["subject_references"] == []
            assert proposal["status"] == (
                "NO_CANDIDATE" if mode in {"unsupported", "mixed"} else "UNAVAILABLE"
            )
        assert "架空の業務値" not in response.text
