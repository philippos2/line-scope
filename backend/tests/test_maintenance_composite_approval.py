"""All maintenance Targets share one approval; composite Execute remains deferred."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from test_maintenance_plan_approval_api import act, client_for, current, headers
from test_maintenance_prepare import create_plan, create_record, prepare, update
from test_maintenance_prepare import service as maintenance_fixture
from test_maintenance_record_create_api import execute


@pytest.fixture
def world(db):
    db, service = maintenance_fixture.__wrapped__(db)
    return db, prepare(service)


def business(db):
    with db.transaction() as c:
        return c.execute(
            "SELECT (SELECT jsonb_agg(to_jsonb(p) ORDER BY maintenance_plan_id) FROM maintenance_plan p) AS plans,"
            "(SELECT count(*) FROM maintenance_record) AS records"
        ).fetchone()


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_entire_composite_can_be_acted_on_without_business_mutation(world, action):
    db, saved = world
    before = business(db)
    with client_for(db) as client:
        result = act(client, saved, action)
        assert result.status_code == 200
        data = result.json()["data"]
        assert (
            data["status"]
            == data["approval_status"]
            == ("APPROVED" if action == "approve" else "REJECTED")
        )
        assert data["update_request_id"] == str(saved.update_request_id)
        assert data["approval_id"] == str(saved.approval_id)
        assert act(client, saved, action).status_code == 409
        inspected = client.get(
            f"/update-requests/{saved.update_request_id}", headers=headers("requester")
        )
        assert inspected.json()["data"]["canonical_snapshot"] == saved.snapshot.data
        assert execute(client, saved).status_code == 400
    assert business(db) == before
    with db.transaction() as c:
        assert c.execute(
            "SELECT details FROM update_audit_event WHERE action=%s", (action.upper(),)
        ).fetchone()["details"] == {"target_count": 3}


@pytest.mark.parametrize(
    "fault", ["version", "missing", "plan_id", "plan_code", "record_id", "record_code"]
)
def test_one_conflicting_target_invalidates_whole_request(world, fault):
    db, saved = world
    with db.transaction() as c:
        if fault in {"version", "missing"}:
            c.execute(
                "UPDATE maintenance_plan SET version=6 WHERE maintenance_plan_id=%s"
                if fault == "version"
                else "DELETE FROM maintenance_plan WHERE maintenance_plan_id=%s",
                (UUID(int=20),),
            )
        elif fault.startswith("plan"):
            target = next(
                t
                for t in saved.snapshot.data["targets"]
                if t["target_type"] == "MaintenancePlan" and t["operation_type"] == "CREATE"
            )
            after = target["after"]
            c.execute(
                "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    after["maintenance_plan_id"] if fault == "plan_id" else UUID(int=100),
                    "OTHER" if fault == "plan_id" else after["plan_code"],
                    after["equipment_id"],
                    after["planned_start"],
                    after["planned_end"],
                    after["plan_status"],
                ),
            )
        else:
            after = next(
                t["after"]
                for t in saved.snapshot.data["targets"]
                if t["target_type"] == "MaintenanceRecord"
            )
            c.execute(
                "INSERT INTO maintenance_record(maintenance_record_id,record_code,equipment_id,performed_at,result) VALUES(%s,%s,%s,%s,%s)",
                (
                    after["maintenance_record_id"] if fault == "record_id" else UUID(int=100),
                    "OTHER" if fault == "record_id" else after["record_code"],
                    after["equipment_id"],
                    after["performed_at"],
                    after["result"],
                ),
            )
    before = business(db)
    with client_for(db) as client:
        result = act(client, saved, "approve")
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == (
            "VERSION_CONFLICT" if fault in {"version", "missing"} else "CREATE_CONFLICT"
        )
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert business(db) == before
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='INVALIDATE'"
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize(
    "token,status", [(None, 401), ("floor", 403), ("production", 403), ("requester", 403)]
)
def test_authentication_and_all_target_permissions(world, token, status):
    db, saved = world
    with client_for(db) as client:
        assert act(client, saved, "approve", token).status_code == status
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_wrong_hash_does_not_retire_composite(world):
    db, saved = world
    with client_for(db) as client:
        result = act(client, saved, "approve", snapshot_hash="0" * 64)
        assert result.status_code == 409
        assert result.json()["errors"][0]["code"] == "APPROVAL_HASH_MISMATCH"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_parallel_approval_has_one_atomic_winner(world):
    db, saved = world
    with client_for(db) as client:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: act(client, saved, "approve"), range(2)))
        assert sorted(r.status_code for r in results) == [200, 409]
    assert current(db, saved)["status"] == "APPROVED"


def test_audit_failure_rolls_back_whole_approval_then_retry_succeeds(world):
    db, saved = world
    with db.transaction() as c:
        c.execute("""CREATE FUNCTION fail_composite_audit() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.action='APPROVE' THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW; END $$""")
        c.execute(
            "CREATE TRIGGER fail_composite_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_composite_audit()"
        )
    with client_for(db) as client:
        result = act(client, saved, "approve")
        assert result.status_code == 500 and "private-secret" not in result.text
        assert current(db, saved)["status"] == "WAITING_APPROVAL"
        with db.transaction() as c:
            c.execute("DROP TRIGGER fail_composite_audit ON update_audit_event")
        assert act(client, saved, "approve").status_code == 200


@pytest.mark.parametrize("kind", ["update_record", "create_record", "update_create"])
def test_each_supported_maintenance_pair_is_approved_as_one_request(db, kind):
    db, service = maintenance_fixture.__wrapped__(db)
    targets = {
        "update_record": [update(), create_record()],
        "create_record": [create_plan("NEW"), create_record()],
        "update_create": [update(), create_plan("NEW")],
    }[kind]
    saved = prepare(service, targets)
    before = business(db)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
        assert execute(client, saved).status_code == 400
    assert business(db) == before
    assert current(db, saved)["status"] == "APPROVED"
