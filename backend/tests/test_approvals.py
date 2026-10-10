from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from test_proposals import context

from linescope.approvals import EquipmentApproval
from linescope.canonical import canonical_hash
from linescope.database import Database
from linescope.demo_seed import DEMO_EQUIPMENT, seed_demo
from linescope.prepare import EquipmentStatePrepare
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def prepared(db):
    db.migrate()
    seed_demo(db)
    saved = EquipmentStatePrepare(db).prepare(
        context("requester"),
        [{"equipment_id": str(DEMO_EQUIPMENT[0][0]), "state_code": "RUNNING"}],
        str(uuid4()),
        agent_input_hash=canonical_hash("explicit equipment update"),
    )
    return db, saved


def approve(db, saved, actor=None, digest=None):
    return EquipmentApproval(db).approve(
        actor or context("approver", "maintenance"),
        str(saved.approval_id),
        digest or saved.snapshot.snapshot_hash,
    )


def test_approval_sets_server_deadline_and_audit_without_business_update(prepared):
    db, saved = prepared
    result = approve(db, saved)
    assert result["status"] == result["approval_status"] == "APPROVED"
    assert result["expires_at"] - result["approved_at"] == timedelta(minutes=30)
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT state_code FROM equipment_current_state WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            ).fetchone()["state_code"]
            == "STOPPED"
        )
        event = c.execute("SELECT * FROM update_audit_event WHERE action='APPROVE'").fetchone()
        assert (
            event["actor_id"] == "approver"
            and event["update_request_id"] == saved.update_request_id
        )
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["expires_at"]
        == result["expires_at"]
    )


@pytest.mark.parametrize(
    "actor,digest,code",
    [
        (context("requester", "maintenance"), None, "AUTHORIZATION_DENIED"),
        (context("approver", "floor"), None, "AUTHORIZATION_DENIED"),
        (None, "0" * 64, "APPROVAL_MISMATCH"),
    ],
)
def test_rejection_does_not_change_pending_state(prepared, actor, digest, code):
    db, saved = prepared
    with pytest.raises(ProposalError) as caught:
        approve(db, saved, actor, digest)
    assert caught.value.code == code
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "WAITING_APPROVAL"
    )


def test_changed_target_commits_invalidation_and_audit(prepared):
    db, saved = prepared
    with db.transaction() as c:
        c.execute(
            "UPDATE equipment_current_state SET version=2 WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        )
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    current = ProposalStore(db).get(context("requester"), str(saved.update_request_id))
    assert current["status"] == current["approval_status"] == "INVALIDATED"
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT result_code FROM update_audit_event WHERE action='INVALIDATE'"
            ).fetchone()["result_code"]
            == "VERSION_CONFLICT"
        )


def test_audit_failure_rolls_back_approval_and_deadline(prepared):
    db, saved = prepared
    with db.transaction() as c:
        c.execute("""CREATE FUNCTION reject_approval_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private-secret'; END $$""")
        c.execute(
            "CREATE TRIGGER reject_approval_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_approval_audit()"
        )
    with pytest.raises(ProposalError):
        approve(db, saved)
    current = ProposalStore(db).get(context("requester"), str(saved.update_request_id))
    assert current["status"] == "WAITING_APPROVAL" and current["approved_at"] is None


def test_parallel_approvals_allow_only_one_transition(prepared):
    db, saved = prepared

    def attempt(_):
        try:
            approve(db, saved)
            return "OK"
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["INVALID_UPDATE_STATE", "OK"]
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='APPROVE'"
            ).fetchone()["n"]
            == 1
        )


def test_any_changed_target_invalidates_the_whole_multi_equipment_request(prepared):
    db, _ = prepared
    saved = EquipmentStatePrepare(db).prepare(
        context("requester"),
        [{"equipment_id": str(item[0]), "state_code": "UNKNOWN"} for item in DEMO_EQUIPMENT],
        str(uuid4()),
        agent_input_hash=canonical_hash("update both equipment"),
    )
    with db.transaction() as c:
        c.execute(
            "UPDATE equipment_current_state SET version=2 WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[1][0],),
        )
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "INVALIDATED"
    )
    with db.transaction() as c:
        assert c.execute(
            "SELECT state_code FROM equipment_current_state ORDER BY equipment_id"
        ).fetchall() == [{"state_code": "STOPPED"}, {"state_code": "RUNNING"}]


def test_old_pending_request_and_unrelated_change_do_not_prevent_approval(prepared):
    db, saved = prepared
    with db.transaction() as c:
        c.execute(
            "UPDATE update_request SET created_at=clock_timestamp()-INTERVAL '60 days' WHERE update_request_id=%s",
            (saved.update_request_id,),
        )
        c.execute(
            "UPDATE equipment_current_state SET version=2 WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[1][0],),
        )
    assert approve(db, saved)["status"] == "APPROVED"


def test_lock_timeout_leaves_pending_request_and_can_be_retried(prepared):
    db, saved = prepared
    bounded = Database(replace(db.settings, lock_ms=50))
    with db.transaction() as c:
        c.execute(
            "SELECT update_request_id FROM update_request WHERE update_request_id=%s FOR UPDATE",
            (saved.update_request_id,),
        )
        with pytest.raises(ProposalError) as caught:
            approve(bounded, saved)
        assert caught.value.code == "RESOURCE_BUSY"
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "WAITING_APPROVAL"
    )
    assert approve(db, saved)["status"] == "APPROVED"


def test_approval_time_is_obtained_after_waiting_for_business_row_lock(prepared):
    db, saved = prepared
    entered = Event()

    class Watching:
        @contextmanager
        def transaction(self):
            with db.transaction() as connection:

                class Connection:
                    def execute(self, query, params=None):
                        if "equipment_current_state" in query and "FOR UPDATE" in query:
                            entered.set()
                        return connection.execute(query, params)

                yield Connection()

    with ThreadPoolExecutor(1) as pool:
        with db.transaction() as c:
            c.execute(
                "SELECT equipment_id FROM equipment_current_state WHERE equipment_id=%s FOR UPDATE",
                (DEMO_EQUIPMENT[0][0],),
            )
            future = pool.submit(approve, Watching(), saved)
            assert entered.wait(5)
            released_after = c.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
        result = future.result(timeout=5)
    assert result["approved_at"] >= released_after


@pytest.mark.parametrize("stage", ["update_request", "update_audit_event"])
def test_core_reject_late_failure_rolls_back_both_states(prepared, stage):
    from psycopg import sql

    db, saved = prepared
    with db.transaction() as c:
        before_approval = c.execute(
            "SELECT * FROM approval WHERE approval_id=%s", (saved.approval_id,)
        ).fetchone()
        before_request = c.execute(
            "SELECT * FROM update_request WHERE update_request_id=%s", (saved.update_request_id,)
        ).fetchone()
        c.execute("""CREATE FUNCTION reject_core_transition() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected reject failure'; END $$""")
        event, condition = (
            ("UPDATE", "NEW.status='REJECTED'")
            if stage == "update_request"
            else ("INSERT", "NEW.action='REJECT'")
        )
        c.execute(
            sql.SQL(
                "CREATE TRIGGER reject_core_transition BEFORE {} ON {} FOR EACH ROW WHEN ({}) EXECUTE FUNCTION reject_core_transition()"
            ).format(sql.SQL(event), sql.Identifier(stage), sql.SQL(condition))
        )
    with pytest.raises(ProposalError) as caught:
        EquipmentApproval(db).reject(context("approver", "maintenance"), str(saved.approval_id))
    assert caught.value.code == "INTERNAL_ERROR"
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT * FROM approval WHERE approval_id=%s", (saved.approval_id,)
            ).fetchone()
            == before_approval
        )
        assert (
            c.execute(
                "SELECT * FROM update_request WHERE update_request_id=%s",
                (saved.update_request_id,),
            ).fetchone()
            == before_request
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='REJECT'"
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='FAILURE'"
            ).fetchone()["n"]
            == 1
        )


def test_core_reject_actor_text_is_bound_and_audited(prepared):
    db, saved = prepared
    actor = "approver'; DROP TABLE equipment; -- 日本語"
    result = EquipmentApproval(db).reject(context(actor, "maintenance"), str(saved.approval_id))
    assert result["status"] == result["approval_status"] == "REJECTED"
    with db.transaction() as c:
        row = c.execute(
            "SELECT * FROM approval WHERE approval_id=%s", (saved.approval_id,)
        ).fetchone()
        assert row["approver_id"] == actor and row["approved_at"] is None
        event = c.execute("SELECT * FROM update_audit_event WHERE action='REJECT'").fetchone()
        assert event["actor_id"] == actor and event["after_status"] == "REJECTED"
        assert c.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 2


@pytest.mark.parametrize("stage", ["update_request", "update_audit_event"])
@pytest.mark.parametrize("conflict", [False, True])
def test_core_approve_late_failure_restores_both_states_and_deadline(prepared, stage, conflict):
    from psycopg import sql

    db, saved = prepared
    with db.transaction() as c:
        if conflict:
            c.execute("UPDATE equipment_current_state SET version=version+1")
        before_approval = c.execute(
            "SELECT * FROM approval WHERE approval_id=%s", (saved.approval_id,)
        ).fetchone()
        before_request = c.execute(
            "SELECT * FROM update_request WHERE update_request_id=%s", (saved.update_request_id,)
        ).fetchone()
        c.execute("""CREATE FUNCTION reject_core_approve() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected transition failure'; END $$""")
        event, condition = (
            ("UPDATE", "NEW.status IN ('APPROVED','INVALIDATED')")
            if stage == "update_request"
            else ("INSERT", "NEW.action IN ('APPROVE','INVALIDATE')")
        )
        c.execute(
            sql.SQL(
                "CREATE TRIGGER reject_core_approve BEFORE {} ON {} FOR EACH ROW WHEN ({}) EXECUTE FUNCTION reject_core_approve()"
            ).format(sql.SQL(event), sql.Identifier(stage), sql.SQL(condition))
        )
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "INTERNAL_ERROR"
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT * FROM approval WHERE approval_id=%s", (saved.approval_id,)
            ).fetchone()
            == before_approval
        )
        assert (
            c.execute(
                "SELECT * FROM update_request WHERE update_request_id=%s",
                (saved.update_request_id,),
            ).fetchone()
            == before_request
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action IN ('APPROVE','INVALIDATE')"
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='FAILURE'"
            ).fetchone()["n"]
            == 1
        )


def test_core_approve_bound_actor_single_clock_and_native_interval(prepared):
    db, saved = prepared
    actor = "approver'; DROP TABLE equipment; -- 日本語"
    result = approve(db, saved, actor=context(actor, "maintenance"))
    with db.transaction() as c:
        row = c.execute(
            "SELECT * FROM approval WHERE approval_id=%s", (saved.approval_id,)
        ).fetchone()
        assert row["approver_id"] == actor
        assert row["approved_at"] == row["updated_at"] == result["approved_at"]
        assert (
            row["expires_at"] == result["expires_at"] == row["approved_at"] + timedelta(minutes=30)
        )
        assert c.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 2
        assert (
            c.execute("SELECT actor_id FROM update_audit_event WHERE action='APPROVE'").fetchone()[
                "actor_id"
            ]
            == actor
        )


@pytest.mark.parametrize(
    "table,key", [("update_request", "update_request_id"), ("approval", "approval_id")]
)
def test_core_locked_proposal_holds_both_row_locks_until_transaction_end(prepared, table, key):
    import psycopg
    from psycopg import sql

    db, saved = prepared
    bounded = Database(replace(db.settings, lock_ms=50))
    identifier = getattr(saved, key)
    statement = sql.SQL("UPDATE {} SET status=status WHERE {}=%s").format(
        sql.Identifier(table), sql.Identifier(key)
    )
    with db.transaction() as holder:
        locked = EquipmentApproval._locked_proposal(holder, str(saved.approval_id))
        assert locked.snapshot.snapshot_hash == saved.snapshot.snapshot_hash
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with bounded.transaction() as contender:
                contender.execute(statement, (identifier,))
    with bounded.transaction() as contender:
        assert contender.execute(statement, (identifier,)).rowcount == 1


def test_core_approval_lock_rechecks_parent_membership(prepared):
    from linescope.core_approval import find_approval_parent, lock_approval

    db, saved = prepared
    with db.transaction() as c:
        assert (
            find_approval_parent(c, saved.approval_id)["update_request_id"]
            == saved.update_request_id
        )
        assert lock_approval(c, saved.approval_id, uuid4()) is None
        assert (
            lock_approval(c, saved.approval_id, saved.update_request_id)["approval_id"]
            == saved.approval_id
        )
