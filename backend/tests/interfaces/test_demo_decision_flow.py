"""Temporary M0 journey: real storage/approval, explicitly mocked comparison."""

from fastapi.testclient import TestClient
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world

from interfaces.test_controlled_action_scenarios import approve_execute, counts, headers
from linescope.interfaces.api import create_app
from linescope.settings import Settings


def demo_client(db, driver, *, llm=None, **settings):
    return TestClient(
        create_app(
            Settings(
                demo_decision_mock=True,
                **settings,
                users={
                    "requester": {"user_id": "maint1", "role": "maintenance"},
                    "approver": {"user_id": "maint2", "role": "maintenance"},
                    "floor": {"user_id": "floor1", "role": "floor"},
                },
            ),
            db,
            graph_driver=driver,
            llm=llm,
        )
    )


def test_comparison_to_approved_execution_and_current_confirmation(
    db, reader_world, adapters, tmp_path
):
    from linescope.application.knowledge_flow import KnowledgeIngestion
    from linescope.integrations.knowledge_factory import knowledge_adapters

    files, index = knowledge_adapters(Settings(knowledge_mock_root=str(tmp_path)))
    KnowledgeIngestion(db, files, index).ingest(
        code="MANUAL-204",
        version=1,
        title="保全資料",
        body="M-204 修理と交換の参考手順".encode(),
    )
    with demo_client(db, adapters[1].driver, knowledge_mock_root=str(tmp_path)) as client:
        response = client.post(
            "/agent", json={"message": "M-204の修理と交換を比較して"}, headers=headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        package = body["data"]["decision_package"]
        assert package["equipment"]["state_code"] == "STOPPED"
        assert package["comparison"]["source"] == "MOCK_FIXTURE"
        assert package["comparison"]["excluded_options"] == ["CONTINUE"]
        constraint = package["comparison"]["options"][3]["blocking_constraints"][0]
        assert constraint["evidence"] == body["evidence"]["state"]
        assert package["comparison"]["required_information"]
        assert package["comparison"]["options"][0]["total_cost"] == 1900000
        assert package["comparison"]["options"][2]["shortage_units_per_hour"] == 30
        assert body["evidence"]["state"] and body["evidence"]["impact"]
        assert package["comparison"]["document_status"] == "MOCK_SEARCH"
        documents = package["comparison"]["document_evidence"]
        assert documents[0]["text"] == "M-204 修理と交換の参考手順"
        assert body["evidence"]["documents"]["citations"] == [documents[0]["citation"]]
        assert body["evidence"]["comparison"]["calculations"][2]["result"] == 1900000

        assert counts(db)["business_update_history"] == 0
        prepared = client.post(
            "/agent",
            json={"message": package["next_actions"]["prepare_message"]},
            headers=headers(),
        )
        assert prepared.status_code == 200
        saved = prepared.json()["data"]
        assert saved["canonical_snapshot"]["targets"][0]["before"]["state_code"] == "STOPPED"
        endpoint = f"/update-requests/{saved['update_request_id']}/execute"
        assert client.post(endpoint, headers=headers()).status_code == 409
        approve_execute(client, saved)
        committed = counts(db)
        assert committed["business_update_history"] == 1
        assert client.post(endpoint, headers=headers()).status_code == 200
        assert counts(db) == committed
        current = client.post(
            "/agent", json={"message": "M-204の修理と交換を比較して"}, headers=headers()
        )
        assert current.status_code == 200
        assert (
            current.json()["data"]["decision_package"]["equipment"]["state_code"]
            == "UNDER_MAINTENANCE"
        )


def test_demo_comparison_does_not_grant_graph_permission(db, reader_world, adapters):
    with demo_client(db, adapters[1].driver) as client:
        response = client.post(
            "/agent", json={"message": "M-204を比較して"}, headers=headers("floor")
        )
        assert response.status_code == 403
        assert counts(db)["business_update_history"] == 0


def test_demo_mode_is_disabled_by_default():
    assert Settings().demo_decision_mock is False


def test_comparison_keeps_facts_and_unknowns_when_knowledge_is_unavailable(
    db, reader_world, adapters, tmp_path
):
    with demo_client(db, adapters[1].driver, knowledge_mock_root=str(tmp_path)) as client:
        result = client.post(
            "/agent", json={"message": "M-204の修理と交換を比較して"}, headers=headers()
        )
    assert result.status_code == 200 and result.json()["status"] == "partial"
    comparison = result.json()["data"]["decision_package"]["comparison"]
    assert comparison["document_status"] == "UNAVAILABLE"
    assert comparison["document_evidence"] == []
    assert result.json()["evidence"]["documents"] == {}
    assert comparison["options"][0]["total_cost"] == 1900000
    assert counts(db)["business_update_history"] == 0


def test_degradation_comparison_does_not_override_current_stopped_state(db, reader_world, adapters):
    with demo_client(db, adapters[1].driver) as client:
        result = client.post(
            "/agent", json={"message": "M-204の次回更新まで30日の損失を比較して"}, headers=headers()
        )
    package = result.json()["data"]["decision_package"]
    values = {item["id"]: item["result"] for item in package["comparison"]["calculations"]}
    assert values["degradation_loss"] == 480000 and values["simple_cost_recovery"] == 150
    assert package["equipment"]["state_code"] == "STOPPED"
    assert package["comparison"]["options"][3]["feasibility"] == "INFEASIBLE"
    assert package["comparison"]["economic_preference"] is None
    assert counts(db)["business_update_history"] == 0


def test_registered_maintenance_flows_into_comparison_after_approved_execution(
    db, reader_world, adapters
):
    with demo_client(db, adapters[1].driver) as client:
        messages = [
            "設備M-204の保全予定DECISION-PLANを開始2026-11-01T00:00:00Z、"
            "終了2026-11-01T01:00:00Z、状態計画済みで登録して",
            "設備M-204の保全実績DECISION-RECORDを実施2026-10-14T00:00:00Z、"
            "結果「軸を点検しました」、保全予定DECISION-PLANに紐づけて登録して",
        ]
        saved_targets = []
        for message in messages:
            response = client.post("/agent", json={"message": message}, headers=headers())
            assert response.status_code == 200
            saved = response.json()["data"]
            saved_targets.append(saved["canonical_snapshot"]["targets"][0]["after"])
            approve_execute(client, saved)
        committed = counts(db)
        response = client.post(
            "/agent", json={"message": "M-204はまた修理するべきか交換を比較して"}, headers=headers()
        )
        assert response.status_code == 200
        body = response.json()
        maintenance = body["data"]["decision_package"]["maintenance"]
        assert maintenance["plans"]["items"] == [saved_targets[0]]
        assert maintenance["records"]["items"] == [saved_targets[1]]
        assert maintenance["retrieval_complete"] and not maintenance["assessment_complete"]
        assert maintenance["consistency"] == "LATEST_PER_CALL"
        assert "future_failure_probability" in maintenance["unknowns"]
        assert body["evidence"]["maintenance"]["records"] == maintenance["records"]["evidence"]
        assert counts(db) == committed


def test_model_only_selects_presentation_order_in_real_decision_api(db, reader_world, adapters):
    from agent.test_read_agent import ScriptedLLM

    from linescope.integrations.llm import LLMReply

    llm = ScriptedLLM(LLMReply('{"order":["REPAIR","SUBSTITUTE"]}', ()))
    with demo_client(db, adapters[1].driver, llm=llm) as client:
        response = client.post(
            "/agent", json={"message": "M-204の修理と代替を比較して"}, headers=headers()
        )
    assert response.status_code == 200
    body = response.json()
    summary = body["data"]["decision_package"]["summary"]
    assert summary["llm_status"] == "VALIDATED_ORDER"
    assert summary["sections"][0]["id"] == "REPAIR"
    assert body["evidence"]["summary"]["llm_scope"] == "PRESENTATION_ORDER_ONLY"
    assert "1,900,000円" in body["answer"] and "継続案を除外" in body["answer"]
    assert counts(db)["business_update_history"] == 0
