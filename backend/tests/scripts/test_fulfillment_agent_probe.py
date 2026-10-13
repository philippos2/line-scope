import copy
import runpy
from pathlib import Path

import pytest
from agent.test_read_agent import ScriptedLLM, call
from fastapi.testclient import TestClient
from graph.test_alternative_facts import M, P
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world

from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.settings import Settings

probe = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/verify_graph_agent.py"))


@pytest.mark.parametrize("scenario", ["alternative", "spof"])
def test_http_success_with_clarification_is_not_a_successful_analysis(scenario):
    with pytest.raises(ValueError, match="GRAPH_TOOL_RESULT_MISSING"):
        probe["validate_fulfillment_result"](
            {"status": "ok", "data": {"needs_input": True, "tool_results": []}}, scenario
        )


@pytest.mark.parametrize("scenario", ["alternative", "spof"])
def test_probe_accepts_real_server_facts_and_rejects_tampered_results(
    db, reader_world, adapters, scenario
):
    tool = (
        "find_alternative_paths"
        if scenario == "alternative"
        else "find_single_point_failure_candidates"
    )
    key = "excluded_nodes" if scenario == "alternative" else "candidate_nodes"

    def typed(node):
        return {"entity_type": node[0], "entity_id": node[1]}

    llm = ScriptedLLM(
        call(tool, {"important_targets": [typed(P)], key: [typed(M)]}),
        LLMReply("構造結果です。", ()),
    )
    settings = Settings(users={"token": {"user_id": "manager1", "role": "manager"}})
    with TestClient(create_app(settings, db, llm=llm, graph_driver=adapters[1].driver)) as client:
        response = client.post(
            "/agent",
            json={"message": "構造成立を調べて"},
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert probe["validate_fulfillment_result"](payload, scenario)["important_targets"] == 1
    for fault in ("partial", "scope", "evidence", "version", "wrong_target"):
        damaged = copy.deepcopy(payload)
        data = damaged["data"]["tool_results"][0]["data"]
        if fault == "partial":
            data["complete"] = False
        elif fault == "scope":
            data["not_evaluated"].remove("SAFETY")
        elif fault == "evidence":
            damaged["evidence"]["tool_results"][0]["representative_paths"] = []
        elif fault == "version":
            damaged["evidence"]["tool_results"][0]["state_versions"] = {}
        else:
            data["important_targets"] = [typed(M)]
        with pytest.raises(ValueError):
            probe["validate_fulfillment_result"](damaged, scenario)
