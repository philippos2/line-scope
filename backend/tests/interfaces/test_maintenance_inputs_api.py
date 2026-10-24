"""Real PostgreSQL workflow through HTTP, including common human controls."""

import io
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from agent.test_read_agent import ScriptedLLM
from domain.test_maintenance_inputs import payload
from fastapi.testclient import TestClient

from interfaces.agent_read_support import explicit_message, selected_input_summary
from linescope.demo_seed import DEMO_EQUIPMENT, seed_demo
from linescope.domain.canonical import canonical_hash, canonical_json
from linescope.domain.snapshot import CanonicalSnapshot
from linescope.execution import ExecutionContext
from linescope.integrations.llm import LLMReply
from linescope.interfaces.api import create_app
from linescope.logging import EventLogger
from linescope.settings import Settings


def settings(role="manager", approver_role="manager"):
    return Settings(
        users={
            "requester": {"user_id": "requester", "role": role},
            "approver": {"user_id": "approver", "role": approver_role},
            "maintenance": {"user_id": "maintenance", "role": "maintenance"},
            "production": {"user_id": "production", "role": "production"},
            "floor": {"user_id": "floor", "role": "floor"},
        }
    )


def headers(token="requester"):
    return {"Authorization": "Bearer " + token}


def client_for(db, *, role="manager", approver_role="manager"):
    return TestClient(
        create_app(settings(role, approver_role), db, EventLogger(stream=io.StringIO()))
    )


@pytest.fixture
def world(db):
    db.migrate()
    seed_demo(db)
    return db


def body(code="MAINTENANCE", identifier=None):
    return {
        "retry_key": str(uuid4()),
        "maintenance_input_id": identifier,
        "input": {
            "input_code": code,
            "equipment_id": str(DEMO_EQUIPMENT[0][0]),
            "payload": payload(),
        },
        "supersedes_update_request_id": None,
    }


def prepare(client, values=None):
    response = client.post("/maintenance-inputs/prepare", json=values or body(), headers=headers())
    assert response.status_code == 200, response.text
    return response.json()["data"]


def approve(client, saved, token="approver"):
    return client.post(
        f"/approvals/{saved['approval_id']}/approve",
        json={"snapshot_hash": saved["snapshot_hash"]},
        headers=headers(token),
    )


def execute(client, saved):
    return client.post(f"/update-requests/{saved['update_request_id']}/execute", headers=headers())


def identifier(saved):
    return saved["canonical_snapshot"]["targets"][0]["target_id"]


def count(db, name):
    assert name in {"maintenance_input", "business_update_history", "graph_outbox"}
    with db.transaction() as connection:
        return connection.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"]


def test_create_approve_execute_read_and_retry_keep_fixed_ids_and_atomic_history(world):
    with client_for(world) as client:
        values = body()
        saved = prepare(client, values)
        assert saved["snapshot_schema_version"] == 5
        assert prepare(client, values)["update_request_id"] == saved["update_request_id"]
        assert count(world, "maintenance_input") == 0
        assert execute(client, saved).status_code == 409
        assert approve(client, saved).status_code == 200
        result = execute(client, saved)
        assert result.status_code == 200, result.text
        assert result.json()["data"]["current_versions"][0]["version_delta"] == 0
        observed = client.get(f"/maintenance-inputs/{identifier(saved)}", headers=headers()).json()[
            "data"
        ]
        assert observed["source"] == "REGISTERED_INPUT" and observed["input"]["version"] == 1
        assert observed["calculation"]["lead_time_hours"] == "336"
        assert observed["calculation"]["downtime_hours"] == "2"
        assert observed["calculation"]["future_failure_probability"] is None
        assert "DROP TABLE" in str(observed)
        assert (
            execute(client, saved).json()["data"]["execution_result"]
            == result.json()["data"]["execution_result"]
        )
        changed = deepcopy(values)
        changed["input"]["payload"]["details"] = "17"
        assert (
            client.post("/maintenance-inputs/prepare", json=changed, headers=headers()).status_code
            == 409
        )
    assert count(world, "maintenance_input") == count(world, "business_update_history") == 1
    with world.transaction() as connection:
        history = connection.execute("SELECT * FROM business_update_history").fetchone()
        assert (
            history["category"] == "MAINTENANCE_INPUT"
            and history["approver_id"] != history["requester_id"]
        )
        assert connection.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] > 0

    llm = ScriptedLLM(LLMReply("将来故障率は90%です", ()))
    with TestClient(create_app(settings(), world, llm=llm)) as agent_client:
        result = agent_client.post(
            "/agent",
            json=explicit_message(
                "M-204の対応計画の入力は？", "maintenance_input", DEMO_EQUIPMENT[0][0]
            ),
            headers=headers(),
        )
        assert result.status_code == 200
        data = result.json()
        candidates = next(
            row["data"]["items"]
            for row in data["data"]["tool_results"]
            if row["tool"] == "search_maintenance_inputs"
        )
        assert [row["maintenance_input_id"] for row in candidates] == [identifier(saved)]
        assert not any(
            row["tool"] == "get_maintenance_input" for row in data["data"]["tool_results"]
        )
        # The user chooses the observed ID, then the existing detail GET evaluates it.
        detail = agent_client.get(f"/maintenance-inputs/{identifier(saved)}", headers=headers())
        assert detail.status_code == 200
        summary, selected = selected_input_summary(
            world,
            ExecutionContext("requester", "manager", uuid4()),
            "maintenance",
            identifier(saved),
        )
        # Each call has its own observation/evaluation timestamp; all business
        # values and the evaluated validity must still agree.
        actual, expected = selected.data, detail.json()["data"]
        assert actual["input"] == expected["input"]
        assert actual["source"] == expected["source"] == "REGISTERED_INPUT"
        assert {k: v for k, v in actual["calculation"].items() if k != "evaluated_at"} == {
            k: v for k, v in expected["calculation"].items() if k != "evaluated_at"
        }
        assert actual["calculation"]["evaluated_at"] >= expected["calculation"]["evaluated_at"]
        assert "調達待ちと作業・停止時間は別です" in summary
        assert "将来故障率は90%です" not in data["answer"] and "将来故障率は90%です" not in summary
        assert selected.evidence["version"] == 1
        assert not llm.requests and not llm.planning_requests

    # A full decision journey also records the prior incident and repair separately.
    with client_for(world) as client:
        incident = body("FAILURE-2021")
        incident["input"]["payload"].update(
            kind="FAILURE_RECORD",
            period_end="2021-01-01T00:00:00Z",
            lead_time_hours=None,
            replacement_cost_jpy=None,
            include_replacement_cost=None,
            past_loss_jpy="120000",
        )
        fault = prepare(client, incident)
        assert approve(client, fault).status_code == execute_after_approve(client, fault) == 200
        repair_values = deepcopy(incident)
        repair_values["retry_key"] = str(uuid4())
        repair_values["input"]["input_code"] = "REPAIR-2021"
        repair_values["input"]["payload"].update(
            kind="REPAIR_RECORD", details="故障後の修理", past_loss_jpy=None
        )
        repair = prepare(client, repair_values)
        assert approve(client, repair).status_code == execute_after_approve(client, repair) == 200
        history = client.post(
            "/maintenance-inputs/search",
            json={
                "filter": {
                    "kind": "FAILURE_RECORD",
                    "period_start": "2020-01-01T00:00:00Z",
                    "period_end": "2021-01-01T00:00:00Z",
                }
            },
            headers=headers(),
        ).json()["data"]
        assert [row["input_code"] for row in history["items"]] == ["FAILURE-2021"]
        outside = client.post(
            "/maintenance-inputs/search",
            json={"filter": {"kind": "FAILURE_RECORD", "period_start": "2021-01-01T00:00:00Z"}},
            headers=headers(),
        ).json()["data"]
        assert outside["items"] == []
        observed_history = client.get(
            f"/maintenance-inputs/{identifier(fault)}", headers=headers()
        ).json()["data"]
        assert observed_history["calculation"]["past_loss_jpy"] == "120000"
        assert observed_history["calculation"]["future_failure_probability"] is None
        # No winner from a tie; both plans must be available for explicit selection.
        plans = [str(uuid4()), str(uuid4())]
        with world.transaction() as connection:
            for index, plan_id in enumerate(plans):
                connection.execute(
                    "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status,version) VALUES (%s,%s,%s,'2090-01-01T00:00:00Z','2090-01-01T04:00:00Z','PLANNED',1)",
                    (plan_id, "NEXT-" + str(index), DEMO_EQUIPMENT[0][0]),
                )
        choices = client.get(
            f"/maintenance-inputs/next-plans/{DEMO_EQUIPMENT[0][0]}", headers=headers()
        ).json()["data"]
        assert (
            choices["selection_status"] == "SELECT_REQUIRED"
            and choices["automatic_state_change"] is False
        )
        assert {row["maintenance_plan_id"] for row in choices["next_candidates"]} == set(plans)
        linked_values = body("LINKED-PLAN")
        linked_values["input"]["payload"]["maintenance_plan_id"] = plans[0]
        linked = prepare(client, linked_values)
        assert approve(client, linked).status_code == execute_after_approve(client, linked) == 200
        with world.transaction() as connection:
            assert (
                connection.execute(
                    "SELECT state_code FROM equipment_current_state WHERE equipment_id=%s",
                    (DEMO_EQUIPMENT[0][0],),
                ).fetchone()["state_code"]
                == "STOPPED"
            )


def test_update_version_conflict_preserves_winning_payload(world):
    with client_for(world) as client:
        original = prepare(client)
        assert (
            approve(client, original).status_code == execute_after_approve(client, original) == 200
        )
        values = body(identifier=identifier(original))
        values["input"]["payload"]["details"] = "17"
        first = prepare(client, values)
        second_values = deepcopy(values)
        second_values["retry_key"] = str(uuid4())
        second_values["input"]["payload"]["details"] = "18"
        second = prepare(client, second_values)
        assert approve(client, first).status_code == approve(client, second).status_code == 200
        assert execute(client, first).status_code == 200
        assert execute(client, second).json()["errors"][0]["code"] == "VERSION_CONFLICT"
        read = client.get(f"/maintenance-inputs/{identifier(original)}", headers=headers()).json()[
            "data"
        ]
        assert read["input"]["version"] == 2 and read["input"]["payload"]["details"] == "17"
        assert (
            client.get(f"/update-requests/{second['update_request_id']}", headers=headers()).json()[
                "data"
            ]["status"]
            == "INVALIDATED"
        )


def execute_after_approve(client, saved):
    return execute(client, saved).status_code


@pytest.mark.parametrize("role", ["floor", "maintenance", "production"])
def test_only_manager_can_prepare(world, role):
    with client_for(world, role=role) as client:
        assert (
            client.post("/maintenance-inputs/prepare", json=body(), headers=headers()).status_code
            == 403
        )
    assert count(world, "maintenance_input") == 0


@pytest.mark.parametrize(
    "role,expected", [("maintenance", 200), ("production", 200), ("floor", 403)]
)
def test_read_and_saved_snapshot_visibility(world, role, expected):
    with client_for(world) as client:
        saved = prepare(client)
        assert approve(client, saved).status_code == 200
        assert execute(client, saved).status_code == 200
        for path in (
            f"/maintenance-inputs/{identifier(saved)}",
            f"/update-requests/{saved['update_request_id']}",
        ):
            assert client.get(path, headers=headers(role)).status_code == expected


def test_self_approval_and_current_role_loss_are_denied_including_completed_replay(world):
    with client_for(world) as client:
        saved = prepare(client)
        assert approve(client, saved, "requester").status_code == 403
        assert approve(client, saved, "maintenance").status_code == 403
        assert approve(client, saved).status_code == 200
    with client_for(world, approver_role="maintenance") as client:
        assert execute(client, saved).json()["errors"][0]["code"] == "APPROVAL_INVALIDATED"
    # Use a fresh proposal; the previous loss correctly retired its approval.
    with client_for(world) as client:
        saved = prepare(client, body("SECOND"))
        assert approve(client, saved).status_code == execute_after_approve(client, saved) == 200
    with client_for(world, role="floor") as client:
        assert execute(client, saved).status_code == 403
        assert (
            client.get(
                f"/update-requests/{saved['update_request_id']}", headers=headers()
            ).status_code
            == 403
        )


def test_audit_failure_rolls_back_business_history_and_approval_consumption(world):
    with client_for(world) as client:
        saved = prepare(client)
        assert approve(client, saved).status_code == 200
        with world.transaction() as connection:
            connection.execute("""CREATE FUNCTION reject_maintenance_input_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action='EXECUTE' THEN RAISE EXCEPTION 'private-econ-secret'; END IF; RETURN NEW; END $$""")
            connection.execute(
                "CREATE TRIGGER maintenance_input_failure BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_maintenance_input_audit()"
            )
        result = execute(client, saved)
        assert result.status_code == 500 and "private-econ-secret" not in result.text
        assert count(world, "maintenance_input") == count(world, "business_update_history") == 0
        observed = client.get(
            f"/update-requests/{saved['update_request_id']}", headers=headers()
        ).json()["data"]
        assert observed["status"] == observed["approval_status"] == "APPROVED"
        with world.transaction() as connection:
            connection.execute("DROP TRIGGER maintenance_input_failure ON update_audit_event")
        assert execute(client, saved).status_code == 200


def test_parallel_replay_and_duplicate_business_key_do_not_double_write(world):
    with client_for(world) as client:
        saved = prepare(client)
        collision = prepare(client)
        assert approve(client, saved).status_code == approve(client, collision).status_code == 200
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: execute(client, saved), range(2)))
        assert all(result.status_code == 200 for result in results)
        assert (
            results[0].json()["data"]["execution_result"]
            == results[1].json()["data"]["execution_result"]
        )
        assert execute(client, collision).json()["errors"][0]["code"] == "CREATE_CONFLICT"
    assert count(world, "maintenance_input") == count(world, "business_update_history") == 1


def test_strict_http_snapshot_version_hash_and_rejection_boundary(world):
    with client_for(world) as client:
        assert client.post("/maintenance-inputs/prepare", json=body()).status_code == 401
        values = body()
        values["user_id"] = "manager"
        assert (
            client.post("/maintenance-inputs/prepare", json=values, headers=headers()).status_code
            == 400
        )
        future = body("FUTURE-INCIDENT")
        future["input"]["payload"].update(
            kind="FAILURE_RECORD",
            lead_time_hours=None,
            replacement_cost_jpy=None,
            include_replacement_cost=None,
        )
        assert (
            client.post("/maintenance-inputs/prepare", json=future, headers=headers()).status_code
            == 422
        )
        bad_link = body("MISSING-PLAN")
        bad_link["input"]["payload"]["maintenance_plan_id"] = str(uuid4())
        assert (
            client.post("/maintenance-inputs/prepare", json=bad_link, headers=headers()).status_code
            == 422
        )
        saved = prepare(client)
        tampered = deepcopy(saved["canonical_snapshot"])
        tampered["schema_version"] = 1
        with pytest.raises(ValueError):
            CanonicalSnapshot(canonical_json(tampered), canonical_hash(tampered))
        mismatch = client.post(
            f"/approvals/{saved['approval_id']}/approve",
            json={"snapshot_hash": "0" * 64},
            headers=headers("approver"),
        )
        assert mismatch.status_code == 409
        rejected = client.post(
            f"/approvals/{saved['approval_id']}/reject", headers=headers("approver")
        )
        assert rejected.status_code == 200 and execute(client, saved).status_code == 409
        assert (
            client.get(f"/maintenance-inputs/{identifier(saved)}", headers=headers()).status_code
            == 404
        )
