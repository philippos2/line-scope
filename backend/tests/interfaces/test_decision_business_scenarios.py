"""Semantic API scenario probes with explicitly registered PG inputs and real Graph.

These partial BS checks do not certify the full business acceptance criteria.
"""

import pytest
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world

from interfaces.test_controlled_action_scenarios import counts, headers
from interfaces.test_controlled_action_scenarios import running_world as running_world
from interfaces.test_demo_decision_flow import demo_client
from linescope.domain.demo_scenarios import scenario_inputs
from linescope.settings import Settings


@pytest.mark.parametrize(
    "scenario",
    [
        "STOPPED",
        "DEGRADED",
        "SAFETY_STOP",
        "SUFFICIENT_CAPACITY",
        "MISSING_LOSS",
        "MISSING_REPAIR_COST",
        "NONADDITIVE_LOSS",
    ],
)
def test_given_scenario_when_comparing_then_return_grounded_partial_package(
    db, running_world, adapters, scenario
):
    from decision_fixture import seed_registered

    selection = seed_registered(db, scenario)
    before = counts(db)
    with demo_client(db, adapters[1].driver, demo_decision_scenario=scenario) as client:
        response = client.post("/decisions/compare", json=selection, headers=headers())
    assert response.status_code == 200, response.text
    body = response.json()
    package = body["data"]["decision_package"]
    assert package["equipment"]["state_code"] == "RUNNING"
    result = package["comparison"]
    assert result["source"] == "REGISTERED_INPUT" and body["status"] == "partial"
    assert result["economic_preference"] is None and result["decision_completeness"] == "PARTIAL"
    assert body["evidence"]["states"][0]["evidence"]["source"] == "POSTGRESQL"
    assert body["evidence"]["impact"]["graph_generation"]
    assert all(value == "UNKNOWN" for value in result["risk"].values())
    assert counts(db) == before
    repair, replacement, continuation, interim, substitute = result["options"]
    economics = {
        row["option"]: row
        for row in package["selected_inputs"]["economic"]["calculation"]["options"]
    }
    if scenario == "STOPPED":
        assert repair["total_cost"] == "1900000" and substitute["shortage_rate"] == "30"
        assert replacement["lead_time_hours"] == "336" and replacement["total_cost"] is None
    elif scenario in {"DEGRADED", "SAFETY_STOP"}:
        assert continuation["total_cost"] == "480000"
        if scenario == "SAFETY_STOP":
            stop = [
                item
                for item in continuation["blocking_constraints"]
                if item["code"] == "HARD_SAFETY_STOP"
            ]
            assert len(stop) == 1 and stop[0]["source"] == "REGISTERED_INPUT"
            assert continuation["feasibility"] == "INFEASIBLE"
    elif scenario == "SUFFICIENT_CAPACITY":
        assert substitute["shortage_rate"] == "0" and substitute["feasibility"] == "UNKNOWN"
        assert substitute["blocking_constraints"] == []
    elif scenario == "MISSING_LOSS":
        assert repair["known_subtotal_jpy"] == "1260000" and repair["total_cost"] is None
        assert "P200" in economics["REPAIR"]["unknown_or_nonindependent_keys"]
    elif scenario == "MISSING_REPAIR_COST":
        assert repair["total_cost"] is None and repair["known_subtotal_jpy"] == "1600000"
        assert "repair" in economics["REPAIR"]["unknown_or_nonindependent_keys"]
    else:
        assert repair["total_cost"] is None and repair["known_subtotal_jpy"] == "940000"
        assert "P100" in economics["REPAIR"]["unknown_or_nonindependent_keys"]


def test_named_fixture_requires_explicit_mock_mode():
    with pytest.raises(ValueError):
        Settings(demo_decision_scenario="SAFETY_STOP")
    with pytest.raises(ValueError):
        Settings(demo_decision_mock=True, demo_decision_scenario="UNRECOGNIZED")


def test_environment_selects_only_server_fixture_and_returns_fresh_inputs(monkeypatch):
    monkeypatch.setenv("LINESCOPE_DEMO_DECISION_MOCK", "true")
    monkeypatch.setenv("LINESCOPE_DEMO_DECISION_SCENARIO", "MISSING_LOSS")
    assert Settings.env().demo_decision_scenario == "MISSING_LOSS"
    changed = scenario_inputs("MISSING_LOSS")
    changed["product_loss_per_hour"]["P-200"] = 0
    assert scenario_inputs("MISSING_LOSS")["product_loss_per_hour"]["P-200"] is None


def test_api_cannot_select_or_overwrite_server_fixture(db, reader_world, adapters):
    with demo_client(db, adapters[1].driver, demo_decision_scenario="MISSING_LOSS") as client:
        response = client.post(
            "/agent",
            json={"message": "M-204を比較して", "demo_scenario": "STOPPED"},
            headers=headers(),
        )
    assert response.status_code == 400
    assert counts(db)["business_update_history"] == 0
