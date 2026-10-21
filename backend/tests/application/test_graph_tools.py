"""Fixed Graph Tool dispatch and Agent handoff against real read adapters."""

import pytest
from agent.test_read_agent import AdmittedPlanAgent, ScriptedLLM, call
from graph.test_analysis_reader import built as built
from graph.test_analysis_traversal import chain as chain
from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_neo4j_generation import target as target
from graph.test_rebuild_control import store as store

from application.test_graph_analysis import context, service
from application.test_graph_analysis import world as world
from linescope.agent.agent_input import AgentInput
from linescope.application.reads import ToolError
from linescope.application.tools import ToolDispatcher
from linescope.integrations.llm import LLMReply

TOOLS = ["trace_downstream_impact", "trace_upstream_dependencies"]


class NoDatabase:
    def for_reads(self):
        return self

    def transaction(self):
        raise AssertionError("No storage access expected")


def test_graph_tools_are_advertised_only_with_a_server_adapter():
    absent = ToolDispatcher(NoDatabase())
    assert not set(TOOLS) & absent.schemas().keys()
    configured = ToolDispatcher(NoDatabase(), graph=object())
    schemas = configured.schemas()
    assert len(schemas) == 33
    assert (
        "省略" in schemas["find_alternative_paths"]["properties"]["explicit_as_of"]["description"]
    )
    assert (
        "now"
        in schemas["find_single_point_failure_candidates"]["properties"]["explicit_as_of"][
            "description"
        ]
    )
    assert "find_single_point_failure_candidates" not in absent.schemas()
    alternative = schemas["find_alternative_paths"]
    assert alternative["required"] == ["important_targets", "excluded_nodes"]
    assert alternative["additionalProperties"] is False
    assert "relation_types" not in alternative["properties"]
    assert "timeout_ms" not in alternative["properties"]
    assert "find_alternative_paths" not in absent.schemas()
    assert schemas["find_common_dependencies"]["required"] == ["targets"]
    assert schemas["find_common_dependencies"]["properties"]["targets"]["minItems"] == 2
    assert "find_common_dependencies" not in absent.schemas()
    for tool in TOOLS:
        schema = schemas[tool]
        assert schema["required"] == ["target"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["target"]["additionalProperties"] is False
        assert "CAN_SUBSTITUTE" not in schema["properties"]["relation_types"]["items"]["enum"]
        assert "timeout_ms" not in schema["properties"]
        assert "role" not in schema["properties"]
        assert schemas["find_single_point_failure_candidates"]["required"] == ["important_targets"]
        schemas[tool]["properties"]["target"]["required"].clear()
        assert configured.schemas()[tool]["properties"]["target"]["required"]
    for name in [
        *TOOLS,
        "find_alternative_paths",
        "find_single_point_failure_candidates",
        "execute",
        "approve",
        "cypher",
    ]:
        with pytest.raises(ToolError) as error:
            absent.run(context(), name, {})
        assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("tool", TOOLS)
def test_agent_retains_real_graph_paths_and_server_evidence(world, tool):
    db, _, origin, _, product, _, _, at = world
    target = {
        "entity_type": "Equipment" if tool == TOOLS[0] else "Product",
        "entity_id": origin if tool == TOOLS[0] else product,
    }
    llm = ScriptedLLM(call(tool, {"target": target}), LLMReply("依存経路を確認しました。", ()))
    request = AgentInput.parse(context(), '{"message":"影響経路を調べて"}', received_at=at)
    dispatcher = ToolDispatcher(db, graph=service(world))
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request)
    assert tool in llm.requests[0][1]
    assert set(TOOLS) - {tool} <= dispatcher.schemas().keys()
    assert not (set(TOOLS) - {tool}) & llm.requests[0][1].keys()
    assert not any(name.startswith("prepare_") for name in llm.requests[0][1])
    assert not result.errors and len(result.observations) == 1
    observation = result.observations[0].result
    assert observation.data["complete"] and len(observation.data["reached_nodes"]) == 2
    assert observation.evidence["state_versions"] == {"Equipment:" + origin: 3}
    assert observation.evidence["representative_paths"] == observation.data["representative_paths"]
    assert result.trace[0]["tool"] == tool and result.trace[0]["code"] == "OK"
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize("role", ["floor", "manager"])
def test_dispatch_preserves_graph_authorization_and_input_validation(role):
    from datetime import datetime, timezone

    from linescope.application.graph_analysis import GraphAnalysis
    from linescope.application.graph_request import GraphLimits
    from linescope.graph.analysis_budget import GraphAnalysisBudget

    class Reader:
        def open(self, budget):
            raise AssertionError("Rejected input must not reach storage")

    graph = GraphAnalysis(
        Reader(),
        None,
        system_limits=GraphLimits(3, 10, 5, 5000),
        budget_factory=GraphAnalysisBudget,
        clock=lambda: datetime.now(timezone.utc),
    )
    dispatcher = ToolDispatcher(NoDatabase(), graph=graph)
    with pytest.raises(ToolError) as error:
        dispatcher.run(context(role), TOOLS[0], {"role": "manager", "cypher": "MATCH (n) RETURN n"})
    assert error.value.code == ("AUTHORIZATION_DENIED" if role == "floor" else "INVALID_ARGUMENT")


def test_agent_preserves_partial_search_without_changing_completeness(world):
    db, _, origin, _, _, _, _, at = world
    llm = ScriptedLLM(
        call(
            TOOLS[0],
            {"target": {"entity_type": "Equipment", "entity_id": origin}, "requested_max_paths": 1},
        ),
        LLMReply("返却経路数の上限で分析は不完全です。", ()),
    )
    request = AgentInput.parse(context(), '{"message":"影響を調べて"}', received_at=at)
    result = AdmittedPlanAgent(ToolDispatcher(db, graph=service(world)), llm).run(
        context(), request
    )
    observation = result.observations[0].result
    assert observation.data["complete"] is False
    assert observation.data["limit_reason"] == "PATH_COUNT"
    assert len(observation.evidence["representative_paths"]) == 1
    assert observation.data["determination"] is None


def test_agent_cannot_publish_graph_facts_while_rebuilding(world):
    db, _, origin, _, _, _, _, at = world
    with db.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
    llm = ScriptedLLM(
        call(TOOLS[0], {"target": {"entity_type": "Equipment", "entity_id": origin}}),
        LLMReply("影響なしです。", ()),
    )
    request = AgentInput.parse(context(), '{"message":"影響を調べて"}', received_at=at)
    result = AdmittedPlanAgent(ToolDispatcher(db, graph=service(world)), llm).run(
        context(), request
    )
    assert not result.observations
    assert result.errors[0]["code"] == "GRAPH_REBUILDING"
    assert result.trace[0]["code"] == "GRAPH_REBUILDING"
    assert result.answer != "影響なしです。"
