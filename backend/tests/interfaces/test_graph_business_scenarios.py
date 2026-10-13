"""Business API acceptance: semantic results, not exact LLM wording.

BS-18 / UC-B01,B13,B15 / AC-G08,G10,G11.
The multi-tool journey covers structural parts of UC-16,19,20 only;
it is not BS-G01 or capacity/safety/economic acceptance.
"""

import pytest
from agent.test_read_agent import ScriptedLLM, call
from fastapi.testclient import TestClient
from graph.test_alternative_facts import M, P, Q
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from graph.test_projection_queue import queued
from sqlalchemy import column, select, table, update
from sqlalchemy.dialects.postgresql.psycopg import dialect

from linescope.graph.administration import GraphAdministration
from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.settings import Settings


def typed(node):
    return {"entity_type": node[0], "entity_id": node[1]}


def execute_fixture_statement(db, statement):
    compiled = statement.compile(dialect=dialect())
    with db.transaction() as connection:
        result = connection.execute(str(compiled), compiled.params)
        return result.fetchall() if statement.is_select else None


def inquire(db, driver, replies, message):
    settings = Settings(
        users={"token": {"user_id": "production1", "role": "production"}}, graph_max_paths=100
    )
    llm = ScriptedLLM(
        *replies, LLMReply("登録情報に基づく結果です。能力・安全性・経済影響は未評価です。", ())
    )
    with TestClient(create_app(settings, db, llm=llm, graph_driver=driver)) as client:
        response = client.post(
            "/agent", json={"message": message}, headers={"Authorization": "Bearer token"}
        )
    return response


@pytest.mark.parametrize(
    "condition,expected",
    [
        ("NO_DOWNSTREAM", "EMPTY"),
        ("PATH_LIMIT", "PARTIAL"),
        ("LAGGING", "GRAPH_NOT_CURRENT"),
        ("ERROR", "GRAPH_UNAVAILABLE"),
        ("REBUILDING", "GRAPH_REBUILDING"),
    ],
)
def test_bs18_analysis_unavailable_is_distinct_from_no_impact(
    db, reader_world, adapters, condition, expected
):
    """Given a known equipment and analysis condition; When asked for impact;
    Then return verified empty/partial data or reject latest Graph analysis.
    """
    generation = reader_world[1]
    arguments = {"target": typed(M)}
    if condition == "NO_DOWNSTREAM":
        # Isolated equipment fixture; canonical registration is rebuilt first.
        for name in ("dependency_relation", "production_operation_equipment_assignment"):
            relation = table(name, column("active"))
            execute_fixture_statement(db, update(relation).values(active=False))
        generation = GraphAdministration(db, adapters[1].driver).rebuild().generation
    elif condition == "PATH_LIMIT":
        arguments["requested_max_paths"] = 1
    elif condition == "LAGGING":
        queued.__wrapped__(db)  # Pending canonical update fixture; no projection.
    else:
        control = table("graph_projection_control", column("fatal_error"), column("rebuild_flag"))
        values = (
            {"fatal_error": "TEST_UNAVAILABLE"} if condition == "ERROR" else {"rebuild_flag": True}
        )
        execute_fixture_statement(db, update(control).values(**values))
    response = inquire(
        db, adapters[1].driver, [call("trace_downstream_impact", arguments)], "M-204の影響を調べて"
    )
    body = response.json()
    if expected in {"EMPTY", "PARTIAL"}:
        assert response.status_code == 200
        result = body["data"]["tool_results"][0]["data"]
        evidence = body["evidence"]["tool_results"][0]
        assert evidence["graph_generation"] == generation
        assert evidence["representative_paths"] == result["representative_paths"]
        if expected == "EMPTY":
            assert body["status"] == "ok" and result["complete"]
            assert result["reached_nodes"] == result["representative_paths"] == []
        else:
            assert body["status"] == "partial" and not result["complete"]
            assert result["limit_reason"] == "PATH_COUNT"
            assert result["reached_nodes"]
    else:
        assert response.status_code == 503
        assert body["errors"][0]["code"] == expected
        assert body["data"]["tool_results"] == body["evidence"]["tool_results"] == []


def test_equipment_investigation_connects_impact_alternatives_and_spof_without_mutation(
    db, reader_world, adapters
):
    """Given stopped M-204 and registered dependencies/one-step substitute;
    When production investigates impact, replacement and single failure points;
    Then preserve affected products, verified paths and structural boundaries.
    """
    important = [typed(P), typed(Q)]
    response = inquire(
        db,
        adapters[1].driver,
        [
            call("trace_downstream_impact", {"target": typed(M)}),
            call(
                "find_alternative_paths",
                {"important_targets": important, "excluded_nodes": [typed(M)]},
            ),
            call(
                "find_single_point_failure_candidates",
                {"important_targets": important, "candidate_nodes": [typed(M)]},
            ),
        ],
        "M-204が停止した。影響製品と代替候補を確認し、単一障害点候補か調べて",
    )
    assert response.status_code == 200 and response.json()["status"] == "ok"
    body = response.json()
    results = [item["data"] for item in body["data"]["tool_results"]]
    evidence = body["evidence"]["tool_results"]
    impact, alternative, spof = results
    assert {
        node["entity_id"] for node in impact["reached_nodes"] if node["entity_type"] == "Product"
    } == {P[1], Q[1]}
    assert impact["direct_nodes"] and impact["indirect_nodes"]
    assert all(
        item["after"]["determination"] == "ESTABLISHED" for item in alternative["target_results"]
    )
    assert len(spof["findings"]) == 2 and all(
        item["determination"] == "NOT_CANDIDATE" for item in spof["findings"]
    )
    for result, source in zip(results, evidence, strict=True):
        assert result["complete"]
        assert source["graph_generation"] == reader_world[1]
        assert source["representative_paths"] == result["representative_paths"]
        assert set(result["not_evaluated"]) == {
            "OPERATIONAL_IMPACT",
            "CAPACITY",
            "SAFETY",
            "ECONOMICS",
        }
    requests = table("update_request", column("update_request_id"))
    assert execute_fixture_statement(db, select(requests)) == []
