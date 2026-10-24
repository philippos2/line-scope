"""H6: twelve server cases; the thirteenth (reject/edit race) is in the UI."""

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from linescope.agent.agent_input import AgentInput, ConversationStore
from linescope.agent.read_agent import ReadAgent
from linescope.agent.read_catalog import BUSINESS_FIELDS, TERMS, literal_read, locate_spans
from linescope.agent.read_scope import PLAN_TOOL
from linescope.agent.scope_check import CHECK_TOOL
from linescope.application.agent_service import AgentApplication
from linescope.application.proposals import ProposalError
from linescope.application.reads import ReadResult, ToolError
from linescope.execution import ExecutionContext
from linescope.integrations.llm import LLMReply, ToolCall

EQUIPMENT = str(UUID(int=7))


class Reads:
    def __init__(self):
        self.calls = []

    def schemas(self):
        return {
            tool: {"type": "object"}
            for tool in ("search_equipment", "get_equipment_state", "get_equipment")
        }

    def run(self, context, tool, arguments, **kwargs):
        self.calls.append((tool, arguments))
        if tool == "search_equipment":
            matched = next(iter(arguments["filter"].values())) == "E-7"
            return ReadResult(
                {
                    "items": [
                        {
                            "equipment_id": EQUIPMENT,
                            "equipment_name": "試験設備",
                            "equipment_code": "E-7",
                        }
                    ]
                    if matched
                    else [],
                    "next_cursor": None,
                },
                {},
            )
        assert tool == "get_equipment_state"
        assert context.role == "manager"
        assert arguments["equipment_id"] == EQUIPMENT
        return ReadResult({"equipment_id": EQUIPMENT, "state_code": "STOPPED", "version": 1}, {})


class Hint:
    def __init__(self, *, invalid=False):
        self.invalid = invalid

    def complete(self, messages, *, schemas, deadline):
        if CHECK_TOOL in schemas:
            return LLMReply("", (ToolCall("check", CHECK_TOOL, {"verdict": "MATCH"}),))
        assert PLAN_TOOL in schemas
        text = [m["content"] for m in messages if m["role"] == "user"][-1]
        return LLMReply(
            "",
            (
                ToolCall(
                    "plan",
                    PLAN_TOOL,
                    {
                        "topics": ["STATE"],
                        "subjects": [{"entity_type": "Equipment", "reference": "E-7"}],
                        "requested_fields": ["registered_state"],
                        "source_spans": [
                            {
                                "text": "invented" if self.invalid else text,
                            }
                        ],
                    },
                ),
            ),
        )


def setup(*, invalid=False, clock=None):
    context = ExecutionContext("requester", "manager", uuid4())
    dispatcher = Reads()
    reader = ReadAgent(dispatcher, Hint(invalid=invalid))
    store = ConversationStore(**({"clock": clock, "ttl_seconds": 1} if clock else {}))
    application = AgentApplication(
        proposals=SimpleNamespace(),
        conversations=store,
        equipment=None,
        maintenance=None,
        production=None,
        read_agent=reader,
    )
    request = AgentInput("E-7、動いてるか？", None, None, None, str(uuid4()))
    return context, dispatcher, store, application, request


def pending(**kwargs):
    from linescope.agent.read_catalog import CATALOG_VERSION
    from linescope.agent.read_confirmation import original_hash
    from linescope.agent.read_scope import ReadScope

    context, reads, store, app, request = setup(**kwargs)
    saved = {
        "kind": "READ_SCOPE",
        "closed": False,
        "hash": original_hash(request),
        "catalog_version": CATALOG_VERSION,
        "scope": ReadScope(
            ("STATE",),
            ({"entity_type": "Equipment", "reference": "E-7"},),
            requested_fields=("registered_state",),
        ),
        "targets": [{"entity_type": "Equipment", "entity_id": EQUIPMENT}],
        "clarification": {"kind": "READ_SCOPE", "status": "PENDING"},
    }
    identity = store.create(context, {"read_scope": saved, "messages": []})
    return (
        context,
        reads,
        store,
        app,
        replace(request, context_id=identity, read_confirmation="ACCEPT"),
    )


def test_u01_invalid_source_span_never_grants_read():
    spans, problem = locate_spans([{"text": "尋ねる内容"}], "対象の尋ねる内容は？")
    assert problem is None and spans == ({"text": "尋ねる内容", "start": 3, "end": 8},)
    assert locate_spans([{"text": "同じ"}], "同じ、同じ")[1] == "SPAN_AMBIGUOUS"
    assert locate_spans([{"text": ""}], "質問")[1] == "SPAN_FORMAT"
    assert locate_spans([{"text": "質問", "start": 0, "end": 2}], "質問")[1] == "SPAN_FORMAT"
    context, reads, _, app, request = setup(invalid=True)
    result = app.run(context, request)
    assert result.analysis.read_clarification is None
    assert result.analysis.answer_sections["read_outcome"] == "SELECTION_REQUIRED"
    assert reads.calls == []
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


def test_u02_unexplained_attribute_is_not_dropped():
    context, reads, _, app, request = setup()
    result = app.run(context, replace(request, message="E-7の保証の登録状態は？"))
    assert all(
        f["predicate"] == "equipment.identity" for f in result.analysis.answer_sections["facts"]
    )
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


def test_u03_literal_text_does_not_bypass_public_selection():
    context, reads, _, app, request = setup()
    result = app.run(context, replace(request, message="E-7の登録状態は？"))
    assert result.analysis.needs_input and result.analysis.read_clarification is None
    assert result.analysis.answer_sections["facts"] == []
    assert result.analysis.answer_sections["read_outcome"] == "SELECTION_REQUIRED"
    assert reads.calls == []


def test_u04_competing_field_meanings_require_confirmation(monkeypatch):
    monkeypatch.setitem(TERMS, "equipment_code", TERMS["registered_state"])
    assert literal_read("E-7の登録状態は？") is None
    context, reads, _, app, request = setup()
    result = app.run(context, replace(request, message="E-7の登録状態は？"))
    assert result.analysis.read_clarification is None
    assert result.analysis.answer_sections["read_outcome"] == "SELECTION_REQUIRED"
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


def test_u05_wrong_answer_type_is_not_a_literal_value():
    assert literal_read("E-7の登録状態はいつ？") is None
    context, reads, _, app, request = setup()
    result = app.run(context, replace(request, message="E-7の登録状態はいつ？"))
    assert result.analysis.read_clarification is None
    assert result.analysis.answer_sections["read_outcome"] == "SELECTION_REQUIRED"
    assert all(
        f["predicate"] == "equipment.identity" for f in result.analysis.answer_sections["facts"]
    )


def test_u06_technical_flag_excluded_without_changing_direct_read():
    from linescope.agent.read_scope import IDENTITY_TOOLS

    assert "active" not in BUSINESS_FIELDS
    assert "get_equipment" in IDENTITY_TOOLS
    assert literal_read("E-7の有効フラグは？") is None
    # Identity/raw getters retain their original contract, not a remapped state.
    assert Reads().schemas()["get_equipment"] == {"type": "object"}


def test_u07_legacy_accept_cannot_bypass_policy_with_retry_header():
    context, reads, _, app, request = pending()
    body = {
        "message": request.message,
        "context_id": request.context_id,
        "read_confirmation": "ACCEPT",
    }
    request = AgentInput.parse(context, json.dumps(body), received_at="2026-10-22T00:00:00Z")
    with pytest.raises(ToolError) as error:
        app.run(context, request, retry_requested=True)
    assert error.value.code == "CONTEXT_EXPIRED"
    assert reads.calls == []


def test_u09_other_owner_cannot_accept():
    _, reads, _, app, request = pending()
    before = len(reads.calls)
    with pytest.raises(ProposalError) as error:
        app.run(ExecutionContext("other", "manager", uuid4()), request)
    assert error.value.code == "AUTHORIZATION_DENIED" and len(reads.calls) == before


def test_u10_exact_ttl_boundary_cannot_accept():
    now = [0.0]
    context, reads, _, app, request = pending(clock=lambda: now[0])
    before = len(reads.calls)
    now[0] = 1.0
    with pytest.raises(ProposalError) as error:
        app.run(context, request)
    assert error.value.code == "CONTEXT_EXPIRED" and len(reads.calls) == before


def test_u11_original_text_change_cannot_accept():
    context, reads, _, app, request = pending()
    before = len(reads.calls)
    with pytest.raises(ToolError) as error:
        app.run(context, replace(request, message=request.message + " "))
    assert error.value.code == "INVALID_ARGUMENT" and len(reads.calls) == before


def test_u12_catalog_version_change_cannot_accept():
    context, reads, store, app, request = pending()
    data = store.get(context, request.context_id)
    data["read_scope"]["catalog_version"] = "old"
    store.update(context, request.context_id, data)
    before = len(reads.calls)
    with pytest.raises(ToolError) as error:
        app.run(context, request)
    assert error.value.code == "CONTEXT_EXPIRED" and len(reads.calls) == before


def test_u13_definition_text_does_not_read_selected_equipment():
    context, reads, _, app, request = setup()
    result = app.run(
        context, replace(request, message="調査対象の設備コードはE-7です。\n登録状態って何？")
    )
    assert reads.calls == [] and result.analysis.needs_input
    assert result.analysis.answer_sections["facts"] == []
    assert result.analysis.read_catalog is not None
