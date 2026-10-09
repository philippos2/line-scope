from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from test_maintenance_plan_approval import approve
from test_maintenance_plan_approval import prepared as plan_prepared
from test_maintenance_prepare import identity, prepare

from linescope.execute import EquipmentExecute, MaintenancePlanUpdateExecute
from linescope.proposals import ProposalError, ProposalStore
from linescope.settings import Settings


@pytest.fixture
def approved(db):
    db, svc, saved = plan_prepared.__wrapped__(db)
    approve(db, saved)
    return db, svc, saved


def settings(role="maintenance"):
    return Settings(users={"token": {"user_id": "approver", "role": role}})


def execute(db, saved, actor=None, role="maintenance"):
    return MaintenancePlanUpdateExecute(db, settings(role)).execute(
        actor or identity(), str(saved.update_request_id)
    )


def test_all_plan_updates_history_consumption_and_immutable_replay(approved):
    db, _, saved = approved
    result = execute(db, saved)
    with db.transaction() as c:
        assert (
            c.execute("SELECT plan_status,version FROM maintenance_plan").fetchall()
            == [{"plan_status": "CANCELLED", "version": 6}] * 2
        )
        history = c.execute("SELECT * FROM business_update_history").fetchone()
        assert (
            history["category"] == "MAINTENANCE" and len(history["after_snapshot"]["targets"]) == 2
        )
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0
        c.execute(
            "UPDATE maintenance_plan SET version=7,plan_status='PLANNED' WHERE maintenance_plan_id=%s",
            (UUID(int=20),),
        )
    assert execute(db, saved, role="floor") == result
    assert result["targets"][0]["after"]["plan_status"] == "CANCELLED"
    assert ProposalStore(db).get(identity(), str(saved.update_request_id))["status"] == "COMPLETED"


def test_conflicting_plan_rejects_all_updates(approved):
    db, _, saved = approved
    with db.transaction() as c:
        c.execute(
            "UPDATE maintenance_plan SET version=6 WHERE maintenance_plan_id=%s", (UUID(int=21),)
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    with db.transaction() as c:
        assert c.execute(
            "SELECT version,plan_status FROM maintenance_plan WHERE maintenance_plan_id=%s",
            (UUID(int=20),),
        ).fetchone() == {"version": 5, "plan_status": "PLANNED"}
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
    assert (
        ProposalStore(db).get(identity(), str(saved.update_request_id))["status"] == "INVALIDATED"
    )


def test_nonowner_and_lost_permission_are_distinct(approved):
    db, _, saved = approved
    with pytest.raises(ProposalError) as caught:
        execute(db, saved, identity("manager", "other"))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    with pytest.raises(ProposalError) as caught:
        execute(db, saved, identity("floor"))
    assert caught.value.code == "APPROVAL_INVALIDATED"
    assert (
        ProposalStore(db).get(identity(), str(saved.update_request_id))["status"] == "INVALIDATED"
    )


def test_audit_failure_rolls_back_all_plans_and_history_then_allows_retry(approved):
    db, _, saved = approved
    with db.transaction() as c:
        c.execute(
            """CREATE FUNCTION reject_execution_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='EXECUTE' THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW; END $$"""
        )
        c.execute(
            "CREATE TRIGGER reject_execution_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_execution_audit()"
        )
    with pytest.raises(ProposalError):
        execute(db, saved)
    with db.transaction() as c:
        assert (
            c.execute("SELECT plan_status,version FROM maintenance_plan").fetchall()
            == [{"plan_status": "PLANNED", "version": 5}] * 2
        )
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
        c.execute("DROP TRIGGER reject_execution_audit ON update_audit_event")
    assert execute(db, saved)["history_id"]


def test_parallel_execution_updates_once(approved):
    db, _, saved = approved
    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(lambda _: execute(db, saved), range(2))
    assert first == second
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1


def test_equipment_entrypoint_rejects_maintenance_even_after_completion(approved):
    db, _, saved = approved
    for completed in (False, True):
        if completed:
            execute(db, saved)
        with pytest.raises(ProposalError) as caught:
            EquipmentExecute(db, settings()).execute(identity(), str(saved.update_request_id))
        assert caught.value.code == "INVALID_ARGUMENT"


def test_create_record_composite_remains_outside_update_scope(approved):
    db, svc, _ = approved
    saved = prepare(svc)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_sql_consumption_guard_rejects_expiry_after_prior_validation(approved):
    from contextlib import contextmanager
    from datetime import timedelta

    db, _, saved = approved
    with db.transaction() as c:
        row = c.execute(
            "WITH t AS (SELECT clock_timestamp()-INTERVAL '31 minutes' AS at) UPDATE approval SET approved_at=t.at,expires_at=t.at+INTERVAL '30 minutes' FROM t RETURNING expires_at"
        ).fetchone()
    prior_time = row["expires_at"] - timedelta(seconds=1)
    reads = 0

    class ClockDb:
        @contextmanager
        def transaction(self):
            with db.transaction() as c:

                class Connection:
                    def execute(self, query, params=None):
                        nonlocal reads
                        if query == "SELECT clock_timestamp() AS now":
                            reads += 1
                            if reads <= 3:

                                class Cursor:
                                    def fetchone(self):
                                        return {"now": prior_time}

                                return Cursor()
                        return c.execute(query, params)

                yield Connection()

    with pytest.raises(ProposalError) as caught:
        MaintenancePlanUpdateExecute(ClockDb(), settings()).execute(
            identity(), str(saved.update_request_id)
        )
    assert caught.value.code == "APPROVAL_EXPIRED"
    with db.transaction() as c:
        assert (
            c.execute("SELECT plan_status,version FROM maintenance_plan").fetchall()
            == [{"plan_status": "PLANNED", "version": 5}] * 2
        )
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
        assert c.execute("SELECT status FROM update_request").fetchone()["status"] == "EXPIRED"
