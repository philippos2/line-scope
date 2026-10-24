"""Existing explicit Read entry and schema checks, without bypassing HTTP admission."""

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


def confirm_read(client, message, headers, **body):
    """Use the real H6 confirmation; do not inject an admitted plan into the app."""
    first = client.post("/agent", json={"message": message, **body}, headers=headers)
    assert first.status_code == 200, first.json()
    pending = first.json()
    assert pending["data"]["read_clarification"]["status"] == "PENDING"
    assert pending["data"]["needs_input"]
    assert all(
        row["tool"]
        in {
            "search_equipment",
            "get_equipment",
            "get_product",
            "get_process",
            "get_production_operation",
            "get_infrastructure_resource",
        }
        for row in pending["data"]["tool_results"]
    )
    return client.post(
        "/agent",
        json={
            "message": message,
            **body,
            "context_id": pending["context_id"],
            "read_confirmation": "ACCEPT",
        },
        headers=headers,
    )


def assert_unconfirmed_prepare_rejected(database, context, message, tool, arguments):
    """The H6 gate may stop early; keep testing the runtime authorization guard too."""
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


def selected_input_summary(database, context, family, identifier):
    """Inspect an explicitly selected input through the real Tool and code renderer.

    This is not a natural-language HTTP success. Callers separately exercise H6
    candidate discovery and the existing detail GET; a model never selects the ID.
    """
    from linescope.agent.grounded_answer import build_answer
    from linescope.agent.read_agent import ReadObservation

    tool = f"get_{family}_input"
    result = ToolDispatcher(database).run(context, tool, {f"{family}_input_id": identifier})
    observation = ReadObservation(str(uuid4()), tool, result)
    answer, sections = build_answer((observation,))
    assert sections["facts"]
    return answer, result


def explicit_message(message, key, equipment_id):
    """An independently selected H7 request; text never selects its field or target."""
    from linescope.agent.read_catalog import CATALOG_VERSION

    return {
        "message": message,
        "read_selection": {
            "operation": "EXECUTE",
            "catalog_version": CATALOG_VERSION,
            "key": key,
            "targets": [{"entity_type": "Equipment", "entity_id": str(equipment_id)}],
        },
    }
