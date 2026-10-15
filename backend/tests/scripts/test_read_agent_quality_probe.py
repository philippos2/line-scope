"""A structured baseline must not certify failed facts or prose quality."""

import runpy
from pathlib import Path

import pytest

from linescope.demo_graph_seed import demo_id
from linescope.demo_seed import DEMO_EQUIPMENT


@pytest.mark.parametrize(
    "scenario,valid",
    [
        (scenario, valid)
        for scenario in ("state_and_cause", "downstream", "missing_equipment")
        for valid in (True, False)
    ],
)
def test_observation_gate_requires_known_fixture_and_missing_target(monkeypatch, scenario, valid):
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    probe = runpy.run_path(str(scripts / "verify_read_agent_quality.py"))
    equipment_id = str(DEMO_EQUIPMENT[0][0])
    tool = "get_equipment_state" if scenario == "state_and_cause" else "trace_downstream_impact"
    data = (
        {"equipment_id": equipment_id, "state_code": "STOPPED" if valid else "RUNNING"}
        if scenario == "state_and_cause"
        else {
            "target": {"entity_type": "Equipment", "entity_id": equipment_id},
            "reached_nodes": [
                {"entity_type": kind, "entity_id": str(demo_id(code))}
                for kind, codes in (
                    ("Process", ("P-10", "P-20")),
                    ("ProductionOperation", ("OP-30", "OP-40")),
                    ("Product", ("P-100", "P-200")),
                )
                for code in codes
            ],
            "complete": valid,
            "graph_sync_state": "CURRENT",
            "analysis_scope": "DEPENDENCY_REACHABILITY",
            "not_evaluated": ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"],
        }
    )
    payload = {
        "status": "ok",
        # Deliberately arbitrary prose: this gate cannot certify it.
        "answer": "文章の根拠品質は別レビューが必要です。",
        "data": {
            "needs_input": False,
            "tool_results": [
                {
                    "tool": "search_equipment",
                    "tool_call_id": "s1",
                    "data": {
                        "items": [] if valid else [{"equipment_id": equipment_id}],
                        "next_cursor": None,
                    },
                }
            ]
            if scenario == "missing_equipment"
            else [{"tool": tool, "tool_call_id": "t1", "data": data}],
        },
        "evidence": {"tool_results": [{"tool": tool, "tool_call_id": "t1"}]},
    }
    if valid:
        probe["validate_observations"](scenario, payload)
    else:
        with pytest.raises(ValueError):
            probe["validate_observations"](scenario, payload)


@pytest.mark.parametrize(
    "scenario,tool",
    [("upstream", "trace_upstream_dependencies"), ("common", "find_common_dependencies")],
)
def test_dependency_probe_requires_fixture_facts_and_complete_search(monkeypatch, scenario, tool):
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    probe = runpy.run_path(str(scripts / "verify_read_agent_quality.py"))
    equipment = {"entity_type": "Equipment", "entity_id": str(DEMO_EQUIPMENT[0][0])}
    nodes = [{"entity_type": "InfrastructureResource", "entity_id": str(demo_id("R-02"))}]
    data = {
        "analysis_scope": "DEPENDENCY_REACHABILITY",
        "graph_sync_state": "CURRENT",
        "complete": True,
        "not_evaluated": ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"],
    }
    if scenario == "common":
        nodes += [equipment] + [
            {"entity_type": kind, "entity_id": str(demo_id(code))}
            for kind, codes in (
                ("Process", ("P-10", "P-20")),
                ("ProductionOperation", ("OP-30", "OP-40")),
            )
            for code in codes
        ]
        data.update(
            targets=[
                {"entity_type": "Product", "entity_id": str(demo_id(code))}
                for code in ("P-100", "P-200")
            ],
            common_candidates=nodes,
        )
    else:
        data.update(target=equipment, reached_nodes=nodes)
    payload = {
        "status": "ok",
        "answer": "要約",
        "data": {"tool_results": [{"tool": tool, "tool_call_id": "g1", "data": data}]},
        "evidence": {"tool_results": [{"tool": tool, "tool_call_id": "g1"}]},
    }
    probe["validate_observations"](scenario, payload)
    data["complete"] = False
    with pytest.raises(ValueError, match="DEPENDENCY_FIXTURE_MISMATCH"):
        probe["validate_observations"](scenario, payload)
