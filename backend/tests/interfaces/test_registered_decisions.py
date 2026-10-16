import pytest
from decision_fixture import seed_registered
from fastapi.testclient import TestClient
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world

from interfaces.test_controlled_action_scenarios import counts
from linescope.domain.canonical import canonical_json
from linescope.interfaces.api import create_app
from linescope.settings import Settings


def auth(role="manager"):
    return {"Authorization": "Bearer " + role}


def client(db, driver, *, llm=None):
    return TestClient(
        create_app(
            Settings(
                users={
                    role: {"user_id": role, "role": role}
                    for role in ("manager", "maintenance", "production", "floor")
                }
            ),
            db,
            graph_driver=driver,
            llm=llm,
        )
    )


@pytest.mark.parametrize("role", ["manager", "maintenance", "production", "floor"])
def test_registered_comparison_role_boundary(db, reader_world, adapters, role):
    selection = seed_registered(db)
    with client(db, adapters[1].driver) as api:
        response = api.post("/decisions/compare", json=selection, headers=auth(role))
    assert response.status_code == (403 if role == "floor" else 200)
    assert counts(db)["business_update_history"] == 0


@pytest.mark.parametrize("change", ["identity", "duplicate", "unknown_field", "reversed_period"])
def test_strict_selection_rejects_untrusted_or_ambiguous_arguments(
    db, reader_world, adapters, change
):
    v = seed_registered(db)
    if change == "identity":
        v["equipment_id"] = "M-204"
    elif change == "duplicate":
        v["capacity_input_ids"] *= 2
    elif change == "unknown_field":
        v["role"] = "manager"
    else:
        v["period_end"] = v["period_start"]
    with client(db, adapters[1].driver) as api:
        assert api.post("/decisions/compare", json=v, headers=auth()).status_code == 400


def test_golden_registered_stop_cost_capacity_plan_and_evidence_without_writes(
    db, reader_world, adapters
):
    selection = seed_registered(db, "SAFETY_STOP")
    before = counts(db)
    with client(db, adapters[1].driver) as api:
        result = api.post("/decisions/compare", json=selection, headers=auth())
        assert result.status_code == 200, result.text
        data = result.json()["data"]
        profile = data["decision_package"]["comparison"]
        assert profile["options"][0]["total_cost"] == "1900000"
        assert profile["options"][2]["feasibility"] == "INFEASIBLE"
        assert any(
            c["code"] == "HARD_SAFETY_STOP" for c in profile["options"][2]["blocking_constraints"]
        )
        assert profile["options"][-1]["shortage_rate"] == "30"
        assert profile["options"][1]["lead_time_hours"] == "336"
        assert len(data["evidence"]["registered_inputs"]) == 4
        assert all(row["input"]["version"] == 1 for row in data["evidence"]["registered_inputs"])
        assert data["decision_package"]["automatic_state_change"] is False
        agent = api.post(
            "/agent",
            json={"message": "登録入力で比較 " + canonical_json(selection)},
            headers=auth(),
        )
        assert agent.status_code == 200 and "候補から除外" in agent.json()["answer"]
        assert "MOCK_FIXTURE" not in result.text and "MOCK_FIXTURE" not in agent.text
    from agent.test_read_agent import ScriptedLLM, call

    from linescope.integrations.llm import LLMReply

    model = ScriptedLLM(
        call("compare_registered_inputs", selection), LLMReply("安全保証、故障率90%。", ())
    )
    with client(db, adapters[1].driver, llm=model) as api:
        result = api.post(
            "/agent",
            json={"message": "登録済みの条件を評価して " + canonical_json(selection)},
            headers=auth(),
        )
        assert result.status_code == 200 and "安全保証" not in result.json()["answer"]
        assert result.json()["status"] == "partial"
        assert "候補から除外" in result.json()["answer"]
        assert result.json()["data"]["tool_results"][0]["tool"] == "compare_registered_inputs"
    assert len(model.requests) == 1  # The verified comparison needs no second model generation.
    temporal_model = ScriptedLLM(
        call("compare_registered_inputs", selection), LLMReply("当時の状態を復元しました", ())
    )
    with client(db, adapters[1].driver, llm=temporal_model) as api:
        response = api.post(
            "/agent",
            json={"message": "登録条件を評価して", "explicit_as_of": "2026-10-01T00:00:00Z"},
            headers=auth(),
        ).json()
        assert not response["data"].get("tool_results")
        assert response["errors"][0]["code"] == "INVALID_ARGUMENT"
    tampered_selection = {**selection, "capacity_input_ids": []}
    tampered_model = ScriptedLLM(
        call("compare_registered_inputs", tampered_selection),
        LLMReply("異なる条件でも問題ありません", ()),
    )
    with client(db, adapters[1].driver, llm=tampered_model) as api:
        response = api.post(
            "/agent",
            json={"message": "次の条件を評価して " + canonical_json(selection)},
            headers=auth(),
        ).json()
        assert not response["data"].get("tool_results")
        assert response["data"]["needs_input"] is True
        assert response["warnings"][0]["code"] == "INVALID_ARGUMENT"
    assert counts(db) == before


def test_missing_inputs_remain_unknown_without_mock_fallback(db, reader_world, adapters):
    selection = seed_registered(db)
    selection.update(
        economic_input_id=None, capacity_input_ids=[], safety_input_ids=[], maintenance_input_ids=[]
    )
    with client(db, adapters[1].driver) as api:
        result = api.post("/decisions/compare", json=selection, headers=auth()).json()
    assert all(
        row["total_cost"] is None
        for row in result["data"]["decision_package"]["comparison"]["options"]
    )
    assert result["status"] == "partial" and "MOCK_FIXTURE" not in str(result)


def test_period_mismatch_does_not_compare_unrelated_horizons(db, reader_world, adapters):
    selection = seed_registered(db)
    selection["period_end"] = "2026-10-03T00:00:00Z"
    with client(db, adapters[1].driver) as api:
        result = api.post("/decisions/compare", json=selection, headers=auth())
    assert (
        result.status_code == 422
        and result.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
    )


def test_economic_input_for_another_equipment_cannot_be_attached(db, reader_world, adapters):
    from linescope.demo_seed import DEMO_EQUIPMENT

    selection = seed_registered(db)
    selection["equipment_id"] = str(DEMO_EQUIPMENT[1][0])
    with client(db, adapters[1].driver) as api:
        assert api.post("/decisions/compare", json=selection, headers=auth()).status_code == 422


def test_current_version_is_refetched_instead_of_replaying_stale_comparison(
    db, reader_world, adapters
):
    selection = seed_registered(db)
    with client(db, adapters[1].driver) as api:
        before = api.post("/decisions/compare", json=selection, headers=auth()).json()["data"]
        with db.transaction() as connection:
            connection.execute(
                "UPDATE economic_input SET version=version+1 WHERE economic_input_id=%s",
                (selection["economic_input_id"],),
            )
        after = api.post("/decisions/compare", json=selection, headers=auth()).json()["data"]
    assert before["evidence"]["registered_inputs"][0]["input"]["version"] == 1
    assert after["evidence"]["registered_inputs"][0]["input"]["version"] == 2
    assert after["decision_package"]["consistency"] == "LATEST_PER_CALL"


def test_noncurrent_graph_fails_closed_before_providing_impact(db, reader_world, adapters):
    selection = seed_registered(db)
    with db.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
    with client(db, adapters[1].driver) as api:
        response = api.post("/decisions/compare", json=selection, headers=auth())
    assert (
        response.status_code == 503 and response.json()["errors"][0]["code"] == "GRAPH_REBUILDING"
    )
    assert response.json()["data"] == {}


def test_upstream_infrastructure_is_not_downstream_damage(db, reader_world, adapters):
    from linescope.demo_graph_seed import demo_id

    selection = seed_registered(db)
    before = counts(db)
    with client(db, adapters[1].driver) as api:
        for path, body in (
            ("/decisions/compare", selection),
            ("/agent", {"message": "登録入力で比較 " + canonical_json(selection)}),
        ):
            response = api.post(path, json=body, headers=auth())
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            package = data["decision_package"]
            upstream = package["upstream_dependencies"]
            resource = {"entity_type": "InfrastructureResource", "entity_id": str(demo_id("R-02"))}
            assert resource in upstream["direct_nodes"]
            assert resource not in package["impact"]["reached_nodes"]
            evidence = data["evidence"] if path != "/agent" else response.json()["evidence"]
            source = evidence["upstream_dependencies"]
            assert (
                source["graph_generation"]
                == evidence["impact"]["graph_generation"]
                == reader_world[1]
            )
            assert source["representative_paths"] == upstream["representative_paths"]
            assert source["graph_observed_at"] and upstream["complete"]
            assert str(demo_id("R-02:SUPPLIES:M-204")) in canonical_json(
                source["representative_paths"]
            )
    assert counts(db) == before


def test_partial_upstream_retains_unknown_and_limit(db, reader_world, adapters, monkeypatch):
    from linescope.application.graph_analysis import GraphAnalysis

    selection = seed_registered(db)
    original = GraphAnalysis.call

    def limited(self, context, tool, arguments):
        if tool == "trace_upstream_dependencies":
            arguments = {**arguments, "requested_max_nodes": 1}
        return original(self, context, tool, arguments)

    monkeypatch.setattr(GraphAnalysis, "call", limited)
    with client(db, adapters[1].driver) as api:
        response = api.post("/decisions/compare", json=selection, headers=auth()).json()
    upstream = response["data"]["decision_package"]["upstream_dependencies"]
    assert response["status"] == "partial"
    assert not upstream["complete"] and upstream["limit_reason"] == "NODE_COUNT"
    assert upstream["reached_nodes"] == []


def test_generation_change_rejects_mixed_analysis(db, reader_world, adapters, monkeypatch):
    from linescope.application.graph_analysis import GraphAnalysis
    from linescope.application.reads import ReadResult

    selection = seed_registered(db)
    original = GraphAnalysis.call

    def switched(self, context, tool, arguments):
        result = original(self, context, tool, arguments)
        if tool == "trace_upstream_dependencies":
            return ReadResult(
                result.data, {**result.evidence, "graph_generation": "changed-generation"}
            )
        return result

    monkeypatch.setattr(GraphAnalysis, "call", switched)
    with client(db, adapters[1].driver) as api:
        response = api.post("/decisions/compare", json=selection, headers=auth())
    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "GRAPH_NOT_CURRENT"
    assert response.json()["data"] == {}
