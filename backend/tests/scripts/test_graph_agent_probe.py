import copy
import runpy
from pathlib import Path

import pytest

from linescope.demo_graph_seed import demo_id
from linescope.demo_seed import DEMO_EQUIPMENT

probe = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/verify_graph_agent.py"))


def fixture():
    nodes = [
        {"entity_type": kind, "entity_id": str(demo_id(code))}
        for kind, codes in (
            ("Process", ("P-10", "P-20")),
            ("ProductionOperation", ("OP-30", "OP-40")),
            ("Product", ("P-100", "P-200")),
        )
        for code in codes
    ]
    root = {"entity_type": "Equipment", "entity_id": str(DEMO_EQUIPMENT[0][0])}
    paths = []
    for node in nodes:
        path_nodes = [root, node]
        if node["entity_type"] == "Product":
            path_nodes = [root, nodes[0], nodes[1], node]
        paths.append({"nodes": path_nodes, "edges": [{} for _ in path_nodes[1:]]})
    return {
        "status": "ok",
        "data": {
            "tool_results": [
                {
                    "tool": "trace_downstream_impact",
                    "tool_call_id": "g1",
                    "data": {
                        "target": {
                            "entity_type": "Equipment",
                            "entity_id": str(DEMO_EQUIPMENT[0][0]),
                        },
                        "complete": True,
                        "graph_sync_state": "CURRENT",
                        "analysis_mode": "CURRENT",
                        "reached_nodes": nodes,
                        "representative_paths": paths,
                    },
                }
            ]
        },
        "evidence": {
            "tool_results": [
                {
                    "tool": "trace_downstream_impact",
                    "tool_call_id": "g1",
                    "graph_generation": "generation1",
                    "representative_paths": copy.deepcopy(paths),
                    "state_versions": {"Equipment:" + str(DEMO_EQUIPMENT[0][0]): 1},
                }
            ]
        },
    }


def test_matching_server_results_pass_without_asserting_llm_prose():
    assert probe["validate_result"](fixture())["affected_products"] == 2


@pytest.mark.parametrize(
    "fault",
    [
        "partial",
        "missing_tool",
        "wrong_target",
        "missing_product",
        "evidence",
        "version",
        "warning",
    ],
)
def test_partial_or_ungrounded_results_fail(fault):
    payload = fixture()
    data = payload["data"]["tool_results"][0]["data"]
    if fault == "partial":
        data["complete"] = False
    elif fault == "missing_tool":
        payload["data"]["tool_results"] = []
    elif fault == "wrong_target":
        data["target"]["entity_id"] = str(DEMO_EQUIPMENT[1][0])
    elif fault == "missing_product":
        data["reached_nodes"].pop()
    elif fault == "evidence":
        payload["evidence"]["tool_results"][0]["representative_paths"] = []
    elif fault == "version":
        payload["evidence"]["tool_results"][0]["state_versions"] = {}
    else:
        payload["warnings"] = [{"code": "RESOURCE_BUSY"}]
    with pytest.raises(ValueError):
        probe["validate_result"](payload)


def test_probe_failure_does_not_print_token_or_external_error(monkeypatch, capsys):
    from urllib.error import HTTPError

    class FailedOpener:
        def open(self, request, timeout):
            assert request.get_header("Authorization") == "Bearer private-token"
            raise HTTPError(request.full_url, 500, "private-token internal detail", {}, None)

    monkeypatch.setenv("LINESCOPE_PROBE_TOKEN", "private-token")
    monkeypatch.setattr("sys.argv", ["verify_graph_agent.py"])
    monkeypatch.setitem(probe["main"].__globals__, "build_opener", lambda handler: FailedOpener())
    assert probe["main"]() == 1
    output = capsys.readouterr().out
    assert "GRAPH_AGENT_PROBE_FAILED" in output
    assert "private-token" not in output and "internal detail" not in output
