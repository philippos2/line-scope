"""Real PostgreSQL workflow through HTTP, including common human controls."""

import io
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from agent.test_read_agent import ScriptedLLM
from domain.test_capacity import payload
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
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO product(product_id,product_code,product_name,active) VALUES (%s,%s,%s,true)",
            ("10000000-0000-4000-8000-000000000001", "P-100", "Test product"),
        )
    return db


def body(code="CAPACITY", identifier=None):
    return {
        "retry_key": str(uuid4()),
        "capacity_input_id": identifier,
        "input": {
            "input_code": code,
            "equipment_id": str(DEMO_EQUIPMENT[0][0]),
            "product_id": "10000000-0000-4000-8000-000000000001",
            "payload": payload(),
        },
        "supersedes_update_request_id": None,
    }


def prepare(client, values=None):
    response = client.post("/capacity-inputs/prepare", json=values or body(), headers=headers())
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
    assert name in {"capacity_input", "business_update_history", "graph_outbox"}
    with db.transaction() as connection:
        return connection.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"]


def test_create_approve_execute_read_and_retry_keep_fixed_ids_and_atomic_history(world):
    with client_for(world) as client:
        candidates = client.post(
            "/capacity-inputs/products/search", json={"query": "P-100"}, headers=headers()
        ).json()["data"]
        assert candidates["items"][0]["product_code"] == "P-100"
        values = body()
        saved = prepare(client, values)
        assert saved["snapshot_schema_version"] == 3
        assert prepare(client, values)["update_request_id"] == saved["update_request_id"]
        assert count(world, "capacity_input") == 0
        assert execute(client, saved).status_code == 409
        assert approve(client, saved).status_code == 200
        result = execute(client, saved)
        assert result.status_code == 200, result.text
        assert result.json()["data"]["current_versions"][0]["version_delta"] == 0
        observed = client.get(f"/capacity-inputs/{identifier(saved)}", headers=headers()).json()[
            "data"
        ]
        assert observed["source"] == "REGISTERED_INPUT" and observed["input"]["version"] == 1
        assert observed["calculation"]["shortage_rate"] == "30"
        assert observed["calculation"]["recovery_status"] == "CONDITIONAL"
        assert "DROP TABLE" in str(observed)
        candidates = client.post(
            "/capacity-inputs/search",
            json={"filter": {"input_code": values["input"]["input_code"]}},
            headers=headers(),
        ).json()["data"]
        assert [row["capacity_input_id"] for row in candidates["items"]] == [identifier(saved)]
        assert "payload" not in candidates["items"][0]
        assert (
            client.post(
                "/capacity-inputs/search",
                json={"filter": {"equipment_query": "%'; DROP TABLE equipment; --"}},
                headers=headers(),
            ).json()["data"]["items"]
            == []
        )
        assert (
            execute(client, saved).json()["data"]["execution_result"]
            == result.json()["data"]["execution_result"]
        )
        changed = deepcopy(values)
        changed["input"]["payload"]["required_rate"] = "91"
        assert (
            client.post("/capacity-inputs/prepare", json=changed, headers=headers()).status_code
            == 409
        )
    assert count(world, "capacity_input") == count(world, "business_update_history") == 1
    with world.transaction() as connection:
        history = connection.execute("SELECT * FROM business_update_history").fetchone()
        assert (
            history["category"] == "CAPACITY_INPUT"
            and history["approver_id"] != history["requester_id"]
        )
        assert connection.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] > 0

    llm = ScriptedLLM(LLMReply("安全で完全代替できます", ()))
    with TestClient(create_app(settings(), world, llm=llm)) as agent_client:
        result = agent_client.post(
            "/agent",
            json=explicit_message("M-204の能力入力は？", "capacity_input", DEMO_EQUIPMENT[0][0]),
            headers=headers(),
        )
        assert result.status_code == 200
        data = result.json()
        candidates = next(
            row["data"]["items"]
            for row in data["data"]["tool_results"]
            if row["tool"] == "search_capacity_inputs"
        )
        assert [row["capacity_input_id"] for row in candidates] == [identifier(saved)]
        assert not any(row["tool"] == "get_capacity_input" for row in data["data"]["tool_results"])
        # The user chooses the observed ID, then the existing detail GET evaluates it.
        detail = agent_client.get(f"/capacity-inputs/{identifier(saved)}", headers=headers())
        assert detail.status_code == 200
        summary, selected = selected_input_summary(
            world, ExecutionContext("requester", "manager", uuid4()), "capacity", identifier(saved)
        )
        assert {k: v for k, v in selected.data.items() if k != "observed_at"} == {
            k: v for k, v in detail.json()["data"].items() if k != "observed_at"
        }
        assert "不足30" in summary and "条件付き許容停止時間4時間" in summary
        assert (
            "安全で完全代替できます" not in data["answer"]
            and "安全で完全代替できます" not in summary
        )
        assert selected.evidence["version"] == 1
        assert not llm.requests and not llm.planning_requests


def test_update_version_conflict_preserves_winning_payload(world):
    with client_for(world) as client:
        original = prepare(client)
        assert (
            approve(client, original).status_code == execute_after_approve(client, original) == 200
        )
        values = body(identifier=identifier(original))
        values["input"]["payload"]["required_rate"] = "91"
        first = prepare(client, values)
        second_values = deepcopy(values)
        second_values["retry_key"] = str(uuid4())
        second_values["input"]["payload"]["required_rate"] = "92"
        second = prepare(client, second_values)
        assert approve(client, first).status_code == approve(client, second).status_code == 200
        assert execute(client, first).status_code == 200
        assert execute(client, second).json()["errors"][0]["code"] == "VERSION_CONFLICT"
        read = client.get(f"/capacity-inputs/{identifier(original)}", headers=headers()).json()[
            "data"
        ]
        assert read["input"]["version"] == 2 and read["input"]["payload"]["required_rate"] == "91"
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
            client.post("/capacity-inputs/prepare", json=body(), headers=headers()).status_code
            == 403
        )
    assert count(world, "capacity_input") == 0


@pytest.mark.parametrize(
    "role,expected", [("maintenance", 200), ("production", 200), ("floor", 403)]
)
def test_read_and_saved_snapshot_visibility(world, role, expected):
    with client_for(world) as client:
        saved = prepare(client)
        assert approve(client, saved).status_code == 200
        assert execute(client, saved).status_code == 200
        for path in (
            f"/capacity-inputs/{identifier(saved)}",
            f"/update-requests/{saved['update_request_id']}",
        ):
            assert client.get(path, headers=headers(role)).status_code == expected
        assert (
            client.post("/capacity-inputs/search", json={}, headers=headers(role)).status_code
            == expected
        )
        assert (
            client.post(
                "/capacity-inputs/products/search", json={}, headers=headers(role)
            ).status_code
            == expected
        )


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
            connection.execute("""CREATE FUNCTION reject_capacity_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action='EXECUTE' THEN RAISE EXCEPTION 'private-econ-secret'; END IF; RETURN NEW; END $$""")
            connection.execute(
                "CREATE TRIGGER capacity_failure BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_capacity_audit()"
            )
        result = execute(client, saved)
        assert result.status_code == 500 and "private-econ-secret" not in result.text
        assert count(world, "capacity_input") == count(world, "business_update_history") == 0
        observed = client.get(
            f"/update-requests/{saved['update_request_id']}", headers=headers()
        ).json()["data"]
        assert observed["status"] == observed["approval_status"] == "APPROVED"
        with world.transaction() as connection:
            connection.execute("DROP TRIGGER capacity_failure ON update_audit_event")
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
    assert count(world, "capacity_input") == count(world, "business_update_history") == 1


def test_strict_http_snapshot_version_hash_and_rejection_boundary(world):
    with client_for(world) as client:
        assert client.post("/capacity-inputs/prepare", json=body()).status_code == 401
        values = body()
        values["user_id"] = "manager"
        assert (
            client.post("/capacity-inputs/prepare", json=values, headers=headers()).status_code
            == 400
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
            client.get(f"/capacity-inputs/{identifier(saved)}", headers=headers()).status_code
            == 404
        )
