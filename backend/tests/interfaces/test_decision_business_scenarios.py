"""Semantic API scenario probes with real PG/Graph and declared mock inputs.

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
    # Given: named server fixture; operational facts still come from real stores.
    before = counts(db)
    with demo_client(db, adapters[1].driver, demo_decision_scenario=scenario) as client:
        # When: the same input goes through the real authenticated API.
        response = client.post(
            "/agent", json={"message": "M-204の修理と交換を比較して"}, headers=headers()
        )
    assert response.status_code == 200
    body = response.json()
    package = body["data"]["decision_package"]
    assert package["equipment"]["state_code"] == "RUNNING"
    result = package["comparison"]
    # Then: numerical/semantic results, not an exact LLM sentence.
    assert result["demo_scenario"] == scenario and result["source"] == "MOCK_FIXTURE"
    assert result["inputs"] == scenario_inputs(scenario)
    assert body["status"] == "partial" and result["decision_completeness"] == "PARTIAL"
    assert result["economic_preference"] is None
    assert body["evidence"]["state"]["source"] == "POSTGRESQL"
    assert body["evidence"]["impact"]["graph_generation"]
    assert all(value == "UNKNOWN" for value in result["risk"].values())
    assert counts(db) == before  # Comparison never prepares or executes a change.
    repair, replacement, substitute, continuation = result["options"]
    if scenario == "STOPPED":  # BS-02/06 numerical slice.
        assert result["economics"]["loss_per_hour"] == 200000
        assert repair["production_loss"] == 1600000 and repair["total_cost"] == 1900000
        assert substitute["shortage_units_per_hour"] == 30
        assert replacement["lead_time_days"] == 14 and replacement["total_cost"] is None
    elif scenario in {"DEGRADED", "SAFETY_STOP"}:  # BS-03/04 partial, not approved safety.
        values = {item["id"]: item["result"] for item in result["calculations"]}
        assert values["degradation_loss"] == 480000 and values["simple_cost_recovery"] == 150
        if scenario == "SAFETY_STOP":
            stop = [
                item
                for item in continuation["blocking_constraints"]
                if item["code"] == "HARD_SAFETY_STOP"
            ]
            assert len(stop) == 1 and stop[0]["source"] == "MOCK_FIXTURE"
            assert continuation["feasibility"] == "INFEASIBLE"
    elif scenario == "SUFFICIENT_CAPACITY":  # BS-05 capacity only, not full substitution.
        assert substitute["shortage_units_per_hour"] == 0
        assert substitute["feasibility"] == "UNKNOWN"
        assert substitute["blocking_constraints"] == []
    elif scenario == "MISSING_LOSS":  # BS-09.
        assert result["economics"]["known_subtotal_per_hour"] == 120000
        assert result["economics"]["loss_per_hour"] is None
        assert result["economics"]["missing_products"] == ["P-200"]
        assert repair["total_cost"] is None
    elif scenario == "MISSING_REPAIR_COST":  # BS-10.
        assert repair["production_loss"] == 1600000 and repair["total_cost"] is None
        assert "repair_cost" in repair["missing_information"]
    else:  # BS-16 nonadditive losses.
        assert result["economics"]["known_subtotal_per_hour"] is None
        assert result["economics"]["loss_per_hour"] is None


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
