"""Existing explicit machine Read and runtime guards; no H6/H7 admission."""

from uuid import uuid4

from linescope.agent.agent_input import AgentInput
from linescope.agent.agent_tools import AgentToolSession
from linescope.application.tools import ToolDispatcher
from linescope.domain.canonical import canonical_json
from linescope.execution import ExecutionContext


def graph_message(tool, arguments):
    return "関係分析 " + canonical_json({"tool": tool, "arguments": arguments})


def readonly_schemas(database):
    context = ExecutionContext("reader", "manager", uuid4())
    request = AgentInput.parse(
        context, '{"message":"参照する"}', received_at="2026-10-13T00:00:00Z"
    )
    return AgentToolSession(context, request, ToolDispatcher(database, graph=object())).schemas()


def assert_unconfirmed_prepare_rejected(database, context, message, tool, arguments):
    """Chat admission does not replace the runtime authorization guard."""
    import json

    import pytest

    from linescope.application.reads import ToolError

    request = AgentInput.parse(
        context, json.dumps({"message": message}), received_at="2026-10-13T00:00:00Z"
    )
    session = AgentToolSession(context, request, ToolDispatcher(database))
    assert tool not in session.schemas()
    with pytest.raises(ToolError) as caught:
        session.run(tool, arguments)
    assert caught.value.code == "AUTHORIZATION_DENIED"


def registered_input_observation(client, category, identifier, headers):
    from types import SimpleNamespace

    from linescope.application.reads import ReadResult

    result = client.get(f"/{category}-inputs/{identifier}", headers=headers)
    assert result.status_code == 200, result.text
    body = result.json()
    return SimpleNamespace(
        tool=f"get_{category}_input", result=ReadResult(body["data"], body["evidence"])
    )
