"""Human assignment APIs distinguish committed diffs from current collections."""

from dataclasses import replace
from uuid import UUID

import pytest
from test_maintenance_plan_approval_api import act, headers
from test_maintenance_record_create_api import execute
from test_production_assignment_execute import assert_committed
from test_production_assignment_prepare import END, NEW_END, START, prepare, target
from test_production_assignment_prepare import service as production_fixture
from test_production_schedule_api import client_for
from test_production_schedule_approval import business, current

from linescope.database import Database
from linescope.graph_locks import acquire_graph_mutation_lock
from linescope.production_assignment_execute import ASSIGNMENT, ProductionAssignmentExecute
from linescope.proposals import ProposalError


@pytest.fixture
def world(db):
    db, service = production_fixture.__wrapped__(db)
    return db, service, prepare(service, [target(20), target(21, equipment=(102,))])


@pytest.mark.parametrize("variant", ["replace", "empty", "noop", "mixed", "middle", "reuse"])
def test_inspection_approval_execution_observes_full_sets_and_diffs(db, variant):
    db, service = production_fixture.__wrapped__(db)
    if variant == "reuse":
        with db.transaction() as c:
            c.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,%s,false,9)",
                (UUID(int=40), UUID(int=20), UUID(int=101), START, END),
            )
    patches = {
        "reuse": [target()],
        "middle": [target(start=END, end=NEW_END)],
        "replace": [target(20), target(21, equipment=(102,))],
        "empty": [target(20, equipment=())],
        "noop": [target(20, equipment=(100,), patch={"planned_status": "CANCELLED"})],
        "mixed": [
            target(20),
            {
                "production_operation_id": str(UUID(int=21)),
                "patch": {"planned_status": "CANCELLED"},
            },
        ],
    }
    saved = prepare(service, patches[variant])
    with client_for(db) as client:
        response = client.get(
            f"/update-requests/{saved.update_request_id}", headers=headers("requester")
        )
        assert response.status_code == 200
        assert response.json()["data"]["canonical_snapshot"] == saved.snapshot.data
        assert act(client, saved, "approve").status_code == 200
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "ok"
        data = response.json()["data"]
        assert [o["snapshot"] for o in data["current_snapshot"]["targets"]] == [
            t["after"] for t in saved.snapshot.data["targets"]
        ]
        assert all(v["version_delta"] == 0 for v in data["current_versions"])
        assert data["observed_at"]
        assert_committed(db, saved, data["execution_result"])
        replay = execute(client, saved).json()["data"]
        assert replay["execution_result"] == data["execution_result"]
        assert_committed(db, saved, replay["execution_result"])


def test_replay_separates_current_parent_collection_and_child_versions(world):
    db, _, saved = world
    child = next(
        t
        for t in saved.snapshot.data["targets"]
        if t["target_type"] == ASSIGNMENT and t["after"]["active"]
    )
    parent_id = child["after"]["production_operation_id"]
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        confirmed = execute(client, saved).json()["data"]["execution_result"]
        with db.transaction() as c:
            c.execute(
                "UPDATE production_operation SET version=version+1 WHERE production_operation_id=%s",
                (parent_id,),
            )
            c.execute(
                "UPDATE production_operation_equipment_assignment SET active=false,version=version+1 WHERE assignment_id=%s",
                (child["target_id"],),
            )
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "ok"
        data = response.json()["data"]
        assert data["execution_result"] == confirmed
        observed = {
            (o["target_type"], o["target_id"]): o["snapshot"]
            for o in data["current_snapshot"]["targets"]
        }
        assert observed[(ASSIGNMENT, child["target_id"])]["active"] is False
        assert child["target_id"] not in {
            a["assignment_id"]
            for a in observed[("ProductionOperation", parent_id)]["equipment_assignments"]
        }
        for v in data["current_versions"]:
            assert v["version_delta"] == int(v["target_id"] in {parent_id, child["target_id"]})
        with db.transaction() as c:
            assert (
                c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1
            )


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(
    "token,status", [(None, 401), ("floor", 403), ("maintenance", 403), ("requester", 403)]
)
def test_human_decisions_require_production_authority_and_other_user(world, action, token, status):
    db, _, saved = world
    before = business(db)
    with client_for(db) as client:
        assert act(client, saved, action, token).status_code == status
    assert current(db, saved)["status"] == "WAITING_APPROVAL" and business(db) == before


@pytest.mark.parametrize("token,status", [(None, 401), ("approver", 403), ("manager", 403)])
def test_execute_requires_original_requester(world, token, status):
    db, _, saved = world
    before = business(db)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, token).status_code == status
    assert current(db, saved)["status"] == "APPROVED" and business(db) == before


@pytest.mark.parametrize("phase", ["approve", "execute"])
def test_changed_assignment_invalidates_entire_update(world, phase):
    db, _, saved = world
    with client_for(db) as client:
        if phase == "execute":
            assert act(client, saved, "approve").status_code == 200
        with db.transaction() as c:
            c.execute(
                "UPDATE production_operation_equipment_assignment SET version=version+1 WHERE production_operation_id=%s",
                (UUID(int=20),),
            )
        before = business(db)
        response = act(client, saved, "approve") if phase == "approve" else execute(client, saved)
        assert (
            response.status_code == 409
            and response.json()["errors"][0]["code"] == "VERSION_CONFLICT"
        )
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before


def test_hash_body_contract_and_rejection(world):
    db, _, saved = world
    with client_for(db) as client:
        response = act(client, saved, "approve", snapshot_hash="0" * 64)
        assert (
            response.status_code == 409
            and response.json()["errors"][0]["code"] == "APPROVAL_HASH_MISMATCH"
        )
        assert (
            client.post(
                f"/approvals/{saved.approval_id}/reject",
                headers=headers("approver"),
                json={"active": False},
            ).status_code
            == 400
        )
        assert act(client, saved, "reject").status_code == 200
        assert execute(client, saved).status_code == 409
    assert current(db, saved)["status"] == "REJECTED"


def test_execute_body_cannot_change_frozen_assignments(world):
    db, _, saved = world
    before = business(db)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved, json={"equipment_ids": []}).status_code == 400
    assert current(db, saved)["status"] == "APPROVED" and business(db) == before


@pytest.mark.parametrize("shared", [True, False])
def test_assignment_api_graph_lock_timeout_is_retryable(world, shared):
    db, _, saved = world
    short = Database(replace(db.settings, lock_ms=50))
    with client_for(short) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as holder:
            acquire_graph_mutation_lock(holder, shared=shared)
            response = execute(client, saved)
        assert (
            response.status_code == 503 and response.json()["errors"][0]["code"] == "RESOURCE_BUSY"
        )
        assert current(db, saved)["status"] == "APPROVED"
        assert execute(client, saved).status_code == 200


@pytest.mark.parametrize(
    "failure", ["missing_child", "missing_parent", "invalid", "dependency", "unexpected"]
)
def test_observation_failure_keeps_completed_result(world, monkeypatch, failure):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        confirmed = execute(client, saved).json()["data"]["execution_result"]
        if failure in {"missing_child", "missing_parent", "invalid"}:
            with db.transaction() as c:
                if failure == "missing_parent":
                    c.execute(
                        "DELETE FROM production_operation_equipment_assignment WHERE production_operation_id=%s",
                        (UUID(int=20),),
                    )
                    c.execute(
                        "DELETE FROM production_operation WHERE production_operation_id=%s",
                        (UUID(int=20),),
                    )
                else:
                    child = next(
                        t
                        for t in saved.snapshot.data["targets"]
                        if t["target_type"] == ASSIGNMENT and t["after"]["active"]
                    )
                    if failure == "missing_child":
                        c.execute(
                            "DELETE FROM production_operation_equipment_assignment WHERE assignment_id=%s",
                            (child["target_id"],),
                        )
                    else:
                        c.execute(
                            "UPDATE production_operation_equipment_assignment SET effective_from='10000-01-01',effective_to=NULL WHERE assignment_id=%s",
                            (child["target_id"],),
                        )
        else:

            def fail(self, result):
                if failure == "unexpected":
                    raise RuntimeError("private-secret")
                raise ProposalError("DEPENDENCY_UNAVAILABLE", "private-secret")

            monkeypatch.setattr(ProductionAssignmentExecute, "observe_current", fail)
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        data = response.json()["data"]
        assert data["status"] == "COMPLETED" and data["approval_status"] == "CONSUMED"
        assert data["execution_result"] == confirmed
        assert data["current_snapshot"] is data["current_versions"] is data["observed_at"] is None
        assert response.json()["warnings"][0]["code"] == (
            "TARGET_NOT_FOUND"
            if failure.startswith("missing")
            else "DEPENDENCY_UNAVAILABLE"
            if failure == "dependency"
            else "INTERNAL_ERROR"
        )
        assert "private-secret" not in response.text


def test_expired_approval_returns_410_without_assignment_writes(world):
    db, _, saved = world
    before = business(db)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as c:
            c.execute(
                "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',expires_at=statement_timestamp()-interval '1 minute'"
            )
        response = execute(client, saved)
        assert (
            response.status_code == 410
            and response.json()["errors"][0]["code"] == "APPROVAL_EXPIRED"
        )
    assert current(db, saved)["status"] == "EXPIRED" and business(db) == before


def test_missing_new_equipment_returns_422_without_partial_update(world):
    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as c:
            c.execute("DELETE FROM equipment WHERE equipment_id=%s", (UUID(int=101),))
        before = business(db)
        response = execute(client, saved)
        assert (
            response.status_code == 422
            and response.json()["errors"][0]["code"] == "BUSINESS_RULE_VIOLATION"
        )
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before


def test_assignment_noop_schedule_change_bypasses_graph_lock(db):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare(service, [target(20, equipment=(100,), patch={"planned_status": "CANCELLED"})])
    assignments = business(db)["assignments"]
    with client_for(Database(replace(db.settings, lock_ms=50))) as client:
        assert act(client, saved, "approve").status_code == 200
        with db.transaction() as holder:
            acquire_graph_mutation_lock(holder, shared=True)
            response = execute(client, saved)
        assert response.status_code == 200 and response.json()["status"] == "ok"
        assert_committed(db, saved, response.json()["data"]["execution_result"])
    assert business(db)["assignments"] == assignments


def test_parallel_http_execute_has_one_history_and_outbox_batch(world):
    from concurrent.futures import ThreadPoolExecutor

    db, _, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda _: execute(client, saved), range(2)))
        assert all(r.status_code == 200 for r in responses)
        results = [r.json()["data"]["execution_result"] for r in responses]
        assert results[0] == results[1]
        assert_committed(db, saved, results[0])
