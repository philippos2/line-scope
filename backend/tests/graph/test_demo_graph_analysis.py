import json

import pytest
from agent.test_read_agent import ScriptedLLM, call
from fastapi.testclient import TestClient

from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_rebuild_controller import adapters as adapters
from linescope.demo_graph_seed import demo_id, seed_graph_demo
from linescope.demo_seed import DEMO_EQUIPMENT
from linescope.graph.administration import GraphAdministration
from linescope.graph.projection_state import ProjectionState
from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.settings import Settings


@pytest.mark.parametrize("direction", ["downstream", "upstream"])
def test_seed_requires_rebuild_and_enables_demo_api(db, adapters, direction):
    db.migrate()
    driver = adapters[1].driver
    administration = GraphAdministration(db, driver)
    seed_graph_demo(db)
    assert ProjectionState(db).observe().status == "ERROR"
    assert ProjectionState(db).observe().active_generation is None
    verified = administration.rebuild()
    assert verified.node_count == 9 and verified.aggregate_count == 10
    target = {"entity_type": "Equipment", "entity_id": str(DEMO_EQUIPMENT[0][0])}
    if direction == "upstream":
        target = {"entity_type": "Product", "entity_id": str(demo_id("P-100"))}
    tool = "trace_downstream_impact" if direction == "downstream" else "trace_upstream_dependencies"
    llm = ScriptedLLM(
        call(tool, {"target": target}),
        LLMReply("影響候補と経路を確認しました。", ()),
    )
    settings = Settings(users={"token": {"user_id": "manager1", "role": "manager"}})
    with TestClient(create_app(settings, db, llm=llm, graph_driver=driver)) as client:
        response = client.post(
            "/agent",
            json={
                "message": "関係分析 " + json.dumps({"tool": tool, "arguments": {"target": target}})
            },
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 200
    data = response.json()["data"]["tool_results"][0]["data"]
    assert data["complete"] and len(data["reached_nodes"]) == 6
    assert data["analysis_scope"] == "DEPENDENCY_REACHABILITY"
    assert data["not_evaluated"] == ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"]
    products = {
        item["entity_id"] for item in data["reached_nodes"] if item["entity_type"] == "Product"
    }
    assert products == (
        {str(demo_id("P-100")), str(demo_id("P-200"))} if direction == "downstream" else set()
    )
    if direction == "upstream":
        assert {
            item["entity_id"]
            for item in data["reached_nodes"]
            if item["entity_type"] == "InfrastructureResource"
        } == {str(demo_id("R-02"))}
    assert {item["entity_type"] for item in data["direct_nodes"]} == {
        "Process",
        "ProductionOperation",
    }
    assert str(DEMO_EQUIPMENT[1][0]) not in {item["entity_id"] for item in data["reached_nodes"]}
    evidence = response.json()["evidence"]["tool_results"][0]
    assert evidence["representative_paths"] == data["representative_paths"]
    if direction == "downstream":
        operation_path = next(
            path
            for path in data["representative_paths"]
            if path["nodes"][-1]["entity_id"] == str(demo_id("OP-40"))
        )
        assert [node["entity_id"] for node in operation_path["nodes"]] == [
            str(DEMO_EQUIPMENT[0][0]),
            str(demo_id("OP-30")),
            str(demo_id("OP-40")),
        ]
        assert [edge["relation_type"] for edge in operation_path["edges"]] == ["USES", "PRECEDES"]
        assert operation_path["edges"][0]["required"] is True
        assert all(data["distances"]["Product:" + identifier] == 3 for identifier in products)
    assert evidence["graph_generation"] == verified.generation
    assert evidence["state_versions"] == {"Equipment:" + str(DEMO_EQUIPMENT[0][0]): 1}
    before = ProjectionState(db).observe()
    seed_graph_demo(db)
    after = ProjectionState(db).observe()
    assert after.status == "CURRENT" and after.active_generation == before.active_generation


def test_new_fixture_rows_after_published_generation_are_rejected(db, adapters):

    from linescope.demo_seed import SeedConflict, seed_demo

    db.migrate()
    administration = GraphAdministration(db, adapters[1].driver)
    old = administration.rebuild()
    for seed in (seed_demo, seed_graph_demo):
        with pytest.raises(SeedConflict):
            seed(db)
        assert ProjectionState(db).observe().status == "CURRENT"
        assert str(ProjectionState(db).observe().active_generation) == old.generation
        with db.transaction() as connection:
            assert connection.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 0
