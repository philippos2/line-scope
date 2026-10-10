"""Record creation validates references under locks and commits all targets together."""

import io
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID

import psycopg
import pytest
from test_maintenance_plan_execute import settings
from test_maintenance_prepare import create_record, identity, prepare
from test_maintenance_record_create_approval import approve, current, insert_conflict
from test_maintenance_record_create_approval import prepared as records_fixture

from linescope.canonical import normalize_timestamp
from linescope.execute import MaintenanceRecordCreateExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError


@pytest.fixture
def approved(db):
    db, service, saved = records_fixture.__wrapped__(db)
    approve(db, saved)
    return db, service, saved


def execute(db, saved, actor=None, role="maintenance"):
    return MaintenanceRecordCreateExecute(
        db, settings(role), EventLogger(stream=io.StringIO())
    ).execute(actor or identity(), str(saved.update_request_id))


def counts(db):
    with db.transaction() as c:
        return c.execute(
            "SELECT (SELECT count(*) FROM maintenance_record) AS records,(SELECT count(*) FROM business_update_history) AS history"
        ).fetchone()


def test_records_history_consumption_and_replay_do_not_mutate_equipment_or_plans(approved):
    db, _, saved = approved
    result = execute(db, saved)
    assert result["targets"] == saved.snapshot.data["targets"]
    assert (
        current(db, saved)["status"] == "COMPLETED"
        and current(db, saved)["approval_status"] == "CONSUMED"
    )
    with db.transaction() as c:
        for target in result["targets"]:
            record = c.execute(
                "SELECT * FROM maintenance_record WHERE maintenance_record_id=%s",
                (target["target_id"],),
            ).fetchone()
            record = {
                **record,
                "maintenance_record_id": str(record["maintenance_record_id"]),
                "equipment_id": str(record["equipment_id"]),
                "maintenance_plan_id": str(record["maintenance_plan_id"])
                if record["maintenance_plan_id"]
                else None,
                "performed_at": normalize_timestamp(record["performed_at"]),
            }
            assert record == target["after"]
        history = c.execute("SELECT * FROM business_update_history").fetchone()
        assert history["category"] == "MAINTENANCE"
        assert all(t["snapshot"] is None for t in history["before_snapshot"]["targets"])
        assert [t["snapshot"] for t in history["after_snapshot"]["targets"]] == [
            t["after"] for t in result["targets"]
        ]
        assert (
            c.execute("SELECT plan_status,version FROM maintenance_plan").fetchall()
            == [{"plan_status": "PLANNED", "version": 5}] * 2
        )
        assert (
            c.execute("SELECT state_code,version FROM equipment_current_state").fetchall()
            == [{"state_code": "RUNNING", "version": 1}] * 2
        )
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0
    assert execute(db, saved, role="floor") == result
    assert counts(db) == {"records": 2, "history": 1}


@pytest.mark.parametrize("id_conflict", [False, True])
def test_collision_after_approval_invalidates_without_partial_records(approved, id_conflict):
    db, _, saved = approved
    insert_conflict(db, saved, id_conflict)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "CREATE_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert counts(db) == {"records": 1, "history": 0}


@pytest.mark.parametrize("fault", ["missing", "different_equipment"])
def test_plan_reference_failure_invalidates_all_records(approved, fault):
    db, _, saved = approved
    with db.transaction() as c:
        if fault == "missing":
            c.execute("DELETE FROM maintenance_plan WHERE maintenance_plan_id=%s", (UUID(int=20),))
        else:
            c.execute(
                "UPDATE maintenance_plan SET equipment_id=%s,version=6 WHERE maintenance_plan_id=%s",
                (UUID(int=11), UUID(int=20)),
            )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert counts(db) == {"records": 0, "history": 0}


def test_missing_equipment_reference_invalidates_all_records(approved):
    db, service, _ = approved
    inputs = [create_record(), create_record(plan_id=None, equipment_id=11)]
    for n, item in enumerate(inputs):
        item["input"]["record_code"] = f"MISSING-{n}"
    saved = prepare(service, inputs)
    approve(db, saved)
    with db.transaction() as c:
        c.execute("DELETE FROM equipment_current_state WHERE equipment_id=%s", (UUID(int=11),))
        c.execute("DELETE FROM equipment WHERE equipment_id=%s", (UUID(int=11),))
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED" and counts(db)["records"] == 0


def test_unrelated_plan_status_version_changes_do_not_invalidate_reference(approved):
    db, _, saved = approved
    with db.transaction() as c:
        c.execute("UPDATE maintenance_plan SET plan_status='CANCELLED',version=6")
    assert execute(db, saved)["history_id"]


def test_share_lock_prevents_plan_reassignment_between_validation_and_insert(approved):
    db, _, saved = approved
    blocked = []

    class LockedDatabase:
        @contextmanager
        def transaction(self):
            with db.transaction() as c:

                class Connection:
                    checked = False

                    def execute(self, query, params=None):
                        if query.startswith("INSERT INTO maintenance_record(") and not self.checked:
                            self.checked = True
                            with pytest.raises(psycopg.errors.LockNotAvailable):
                                with db.transaction() as writer:
                                    writer.execute("SET LOCAL lock_timeout='50ms'")
                                    writer.execute(
                                        "UPDATE maintenance_plan SET equipment_id=%s WHERE maintenance_plan_id=%s",
                                        (UUID(int=11), UUID(int=20)),
                                    )
                            blocked.append(True)
                        return c.execute(query, params)

                yield Connection()

    assert execute(LockedDatabase(), saved)["history_id"]
    assert blocked == [True] and counts(db) == {"records": 2, "history": 1}


@pytest.mark.parametrize("fault", ["second_insert", "audit", "suppressed_insert"])
def test_technical_failure_rolls_back_and_retry_can_complete(approved, fault):
    db, _, saved = approved
    with db.transaction() as c:
        if fault == "audit":
            table = "update_audit_event"
            body = (
                "IF NEW.action='EXECUTE' THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW;"
            )
        elif fault == "suppressed_insert":
            table = "maintenance_record"
            body = "RETURN NULL;"
        else:
            table = "maintenance_record"
            body = "IF NEW.record_code='REC-B' THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW;"
        c.execute(
            f"CREATE FUNCTION fail_record() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$"
        )
        c.execute(
            f"CREATE TRIGGER fail_record BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fail_record()"
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == "APPROVED" and counts(db) == {"records": 0, "history": 0}
    with db.transaction() as c:
        c.execute(f"DROP TRIGGER fail_record ON {table}")
    assert execute(db, saved)["history_id"]


@pytest.mark.parametrize("target_count", [1, 2])
def test_racing_requests_conflict_at_unique_constraint_after_prechecks(approved, target_count):
    db, service, _ = approved
    inputs = [create_record(plan_id=None) for _ in range(target_count)]
    for n, item in enumerate(inputs):
        item["input"]["record_code"] = f"RACE-{n}"
    requests = [prepare(service, inputs), prepare(service, list(reversed(inputs)))]
    for saved in requests:
        approve(db, saved)
    barrier = Barrier(2)

    class RacingDatabase:
        @contextmanager
        def transaction(self):
            with db.transaction() as c:

                class Connection:
                    waited = False

                    def execute(self, query, params=None):
                        if query.startswith("INSERT INTO maintenance_record(") and not self.waited:
                            self.waited = True
                            barrier.wait(timeout=10)
                        return c.execute(query, params)

                yield Connection()

    def attempt(saved):
        try:
            return execute(RacingDatabase(), saved)["history_id"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, requests))
    assert results.count("CREATE_CONFLICT") == 1
    assert sorted(current(db, saved)["status"] for saved in requests) == [
        "COMPLETED",
        "INVALIDATED",
    ]
    assert counts(db) == {"records": target_count, "history": 1}


def test_same_request_parallel_execute_inserts_once(approved):
    db, _, saved = approved
    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(lambda _: execute(db, saved), range(2))
    assert first == second and counts(db) == {"records": 2, "history": 1}


@pytest.mark.parametrize(
    "actor,role,code",
    [
        (identity("manager", "other"), "maintenance", "AUTHORIZATION_DENIED"),
        (identity("floor"), "maintenance", "APPROVAL_INVALIDATED"),
        (identity(), "floor", "APPROVAL_INVALIDATED"),
    ],
)
def test_owner_and_current_permissions(approved, actor, role, code):
    db, _, saved = approved
    with pytest.raises(ProposalError) as caught:
        execute(db, saved, actor, role)
    assert caught.value.code == code and counts(db)["records"] == 0


def test_expired_approval_does_not_insert(approved):
    db, _, saved = approved
    with db.transaction() as c:
        c.execute(
            "WITH t AS (SELECT clock_timestamp()-INTERVAL '31 minutes' AS at) UPDATE approval SET approved_at=t.at,expires_at=t.at+INTERVAL '30 minutes' FROM t WHERE approval_id=%s",
            (saved.approval_id,),
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED" and counts(db)["records"] == 0
