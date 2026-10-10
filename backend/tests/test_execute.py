from concurrent.futures import ThreadPoolExecutor

import pytest
from test_approvals import approve
from test_approvals import prepared as equipment_prepared
from test_proposals import context

from linescope.demo_seed import DEMO_EQUIPMENT
from linescope.execute import EquipmentExecute
from linescope.proposals import ProposalError, ProposalStore
from linescope.settings import Settings


@pytest.fixture
def approved(db):
    db, saved = equipment_prepared.__wrapped__(db)
    approve(db, saved)
    return db, saved


def service(db, role="maintenance"):
    return EquipmentExecute(db, Settings(users={"token": {"user_id": "approver", "role": role}}))


def current(db, saved):
    return ProposalStore(db).get(context("requester"), str(saved.update_request_id))


def test_atomic_execution_and_replay_preserve_confirmed_after(approved):
    db, saved = approved
    result = service(db).execute(context("requester"), str(saved.update_request_id))
    assert result["targets"][0]["after"]["version"] == 2
    assert current(db, saved)["status"] == "COMPLETED"
    with db.transaction() as c:
        assert c.execute("SELECT status FROM approval").fetchone()["status"] == "CONSUMED"
        history = c.execute("SELECT * FROM business_update_history").fetchone()
        request = c.execute("SELECT * FROM update_request").fetchone()
        approval = c.execute("SELECT * FROM approval").fetchone()
        assert str(history["history_id"]) == result["history_id"]
        assert (
            history["occurred_at"].isoformat(timespec="microseconds").replace("+00:00", "Z")
            == result["executed_at"]
        )
        assert (
            history["before_snapshot"]["targets"][0]["snapshot"] == result["targets"][0]["before"]
        )
        assert history["after_snapshot"]["targets"][0]["snapshot"] == result["targets"][0]["after"]
        assert request["execution_result"] == result
        assert request["updated_at"] == approval["consumed_at"]
        assert history["occurred_at"] <= approval["consumed_at"] < approval["expires_at"]
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 1
        c.execute(
            "UPDATE equipment_current_state SET state_code='UNKNOWN',version=3 WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        )
    assert (
        service(db, "floor").execute(context("requester"), str(saved.update_request_id)) == result
    )
    assert result["targets"][0]["after"]["state_code"] == "RUNNING"


def test_nonowner_cannot_execute_or_invalidate(approved):
    db, saved = approved
    with pytest.raises(ProposalError) as caught:
        service(db).execute(context("approver", "manager"), str(saved.update_request_id))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert current(db, saved)["status"] == "APPROVED"


@pytest.mark.parametrize(
    "cause,status,code",
    [
        ("version", "INVALIDATED", "VERSION_CONFLICT"),
        ("role", "INVALIDATED", "APPROVAL_INVALIDATED"),
        ("expiry", "EXPIRED", "APPROVAL_EXPIRED"),
    ],
)
def test_business_failure_revalidated_and_retired_in_separate_transaction(
    approved, cause, status, code
):
    db, saved = approved
    with db.transaction() as c:
        if cause == "version":
            c.execute(
                "UPDATE equipment_current_state SET version=2 WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            )
        if cause == "expiry":
            c.execute(
                "WITH t AS (SELECT clock_timestamp()-INTERVAL '31 minutes' AS at) UPDATE approval SET approved_at=t.at,expires_at=t.at+INTERVAL '30 minutes' FROM t"
            )
    with pytest.raises(ProposalError) as caught:
        service(db, "floor" if cause == "role" else "maintenance").execute(
            context("requester"), str(saved.update_request_id)
        )
    assert caught.value.code == code
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == status
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0


def test_audit_failure_rolls_back_business_history_consumption_and_result(approved):
    db, saved = approved
    with db.transaction() as c:
        c.execute(
            """CREATE FUNCTION fail_execute_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'secret'; END $$"""
        )
        c.execute(
            "CREATE TRIGGER fail_execute_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_execute_audit()"
        )
    with pytest.raises(ProposalError):
        service(db).execute(context("requester"), str(saved.update_request_id))
    assert current(db, saved)["status"] == "APPROVED"
    with db.transaction() as c:
        assert c.execute(
            "SELECT state_code,version FROM equipment_current_state WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        ).fetchone() == {"state_code": "STOPPED", "version": 1}
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
        c.execute("DROP TRIGGER fail_execute_audit ON update_audit_event")
    assert service(db).execute(context("requester"), str(saved.update_request_id))["history_id"]


def test_parallel_execute_returns_same_result_and_updates_once(approved):
    db, saved = approved

    def execute(_):
        return service(db).execute(context("requester"), str(saved.update_request_id))

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.map(execute, range(2))
    assert a == b
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT version FROM equipment_current_state WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            ).fetchone()["version"]
            == 2
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='EXECUTE'"
            ).fetchone()["n"]
            == 1
        )


def test_one_conflicting_equipment_prevents_all_target_updates(approved):
    from uuid import uuid4

    from linescope.canonical import canonical_hash
    from linescope.prepare import EquipmentStatePrepare

    db, _ = approved
    saved = EquipmentStatePrepare(db).prepare(
        context("requester"),
        [{"equipment_id": str(e[0]), "state_code": "UNKNOWN"} for e in DEMO_EQUIPMENT],
        str(uuid4()),
        agent_input_hash=canonical_hash("both"),
    )
    approve(db, saved)
    with db.transaction() as c:
        c.execute(
            "UPDATE equipment_current_state SET version=2 WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[1][0],),
        )
    with pytest.raises(ProposalError) as caught:
        service(db).execute(context("requester"), str(saved.update_request_id))
    assert caught.value.code == "VERSION_CONFLICT"
    with db.transaction() as c:
        assert c.execute(
            "SELECT state_code,version FROM equipment_current_state WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        ).fetchone() == {"state_code": "STOPPED", "version": 1}
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0


def test_expiration_immediately_before_consumption_rolls_back_all_changes(approved):
    from contextlib import contextmanager
    from datetime import timedelta

    db, saved = approved
    initial = current(db, saved)
    deadline = initial["expires_at"]
    ticks = iter([deadline - timedelta(minutes=2), deadline - timedelta(minutes=1)])

    class ClockDatabase:
        @contextmanager
        def transaction(self):
            with db.transaction() as c:

                class Connection:
                    def execute(self, query, params=None):
                        if query == "SELECT clock_timestamp() AS now":

                            class Cursor:
                                def fetchone(self):
                                    return {"now": next(ticks, deadline)}

                            return Cursor()
                        return c.execute(query, params)

                yield Connection()

    with pytest.raises(ProposalError) as caught:
        service(ClockDatabase()).execute(context("requester"), str(saved.update_request_id))
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED"
    with db.transaction() as c:
        assert c.execute(
            "SELECT state_code,version FROM equipment_current_state WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        ).fetchone() == {"state_code": "STOPPED", "version": 1}
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "cause,status,action",
    [("version", "INVALIDATED", "INVALIDATE"), ("expiry", "EXPIRED", "EXPIRE")],
)
def test_retirement_audit_failure_rolls_back_both_states_and_retry_retires(
    approved, cause, status, action
):
    db, saved = approved
    with db.transaction() as c:
        if cause == "version":
            c.execute("UPDATE equipment_current_state SET version=2")
        else:
            c.execute(
                "WITH t AS (SELECT clock_timestamp()-INTERVAL '31 minutes' AS at) "
                "UPDATE approval SET approved_at=t.at,expires_at=t.at+INTERVAL '30 minutes' FROM t"
            )
        before_approval = c.execute("SELECT * FROM approval").fetchone()
        before_request = c.execute("SELECT * FROM update_request").fetchone()
        c.execute("""CREATE FUNCTION reject_retirement_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action IN ('EXPIRE','INVALIDATE') THEN RAISE EXCEPTION 'private-retirement-secret'; END IF;
            RETURN NEW; END $$""")
        c.execute(
            "CREATE TRIGGER reject_retirement_audit BEFORE INSERT ON update_audit_event "
            "FOR EACH ROW EXECUTE FUNCTION reject_retirement_audit()"
        )
    with pytest.raises(ProposalError) as caught:
        service(db).execute(context("requester"), str(saved.update_request_id))
    assert caught.value.code == "INTERNAL_ERROR"
    assert "private-retirement-secret" not in str(caught.value)
    with db.transaction() as c:
        assert c.execute("SELECT * FROM approval").fetchone() == before_approval
        assert c.execute("SELECT * FROM update_request").fetchone() == before_request
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action=%s", (action,)
            ).fetchone()["n"]
            == 0
        )
        c.execute("DROP TRIGGER reject_retirement_audit ON update_audit_event")
    with pytest.raises(ProposalError) as retry:
        service(db).execute(context("requester"), str(saved.update_request_id))
    assert retry.value.code == ("VERSION_CONFLICT" if cause == "version" else "APPROVAL_EXPIRED")
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == status
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action=%s", (action,)
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("table", ["update_request", "approval"])
def test_core_execution_load_holds_request_and_approval_locks_until_transaction_end(
    approved, table
):
    from dataclasses import replace

    import psycopg
    from psycopg import sql

    from linescope.database import Database

    db, saved = approved
    bounded = Database(replace(db.settings, lock_ms=50))
    statement = sql.SQL("UPDATE {} SET status=status WHERE update_request_id=%s").format(
        sql.Identifier(table)
    )
    with db.transaction() as holder:
        row, loaded, facts = service(db)._load(holder, saved.update_request_id)
        assert row["status"] == "APPROVED"
        assert loaded.snapshot == saved.snapshot
        assert facts["snapshot_hash"] == saved.snapshot.snapshot_hash
        assert facts["approver_id"] == "approver" and facts["consumed_at"] is None
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with bounded.transaction() as contender:
                contender.execute(statement, (saved.update_request_id,))
    with bounded.transaction() as contender:
        assert contender.execute(statement, (saved.update_request_id,)).rowcount == 1
