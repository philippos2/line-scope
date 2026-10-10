"""Internal record CREATE approval, with no record or equipment mutations."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from test_maintenance_plan_approval_api import act, client_for
from test_maintenance_prepare import create_record, identity, prepare
from test_maintenance_prepare import service as maintenance_fixture

from linescope.approvals import MaintenanceRecordCreateApproval
from linescope.logging import EventLogger
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def prepared(db):
    db, service = maintenance_fixture.__wrapped__(db)
    linked, unlinked = create_record(), create_record(plan_id=None)
    linked["input"]["record_code"] = "REC-A"
    unlinked["input"]["record_code"] = "REC-B"
    return db, service, prepare(service, [linked, unlinked])


def current(db, saved):
    return ProposalStore(db).get(identity(), str(saved.update_request_id))


def approve(db, saved, *, actor=None, snapshot_hash=None, stream=None):
    return MaintenanceRecordCreateApproval(db, EventLogger(stream=stream or io.StringIO())).approve(
        actor or identity(user="approver"),
        str(saved.approval_id),
        snapshot_hash or saved.snapshot.snapshot_hash,
    )


def insert_conflict(db, saved, id_conflict):
    after = saved.snapshot.data["targets"][0]["after"]
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO maintenance_record(maintenance_record_id,record_code,equipment_id,performed_at,result,maintenance_plan_id) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                after["maintenance_record_id"] if id_conflict else uuid4(),
                "OTHER-RECORD" if id_conflict else after["record_code"],
                after["equipment_id"],
                after["performed_at"],
                after["result"],
                after["maintenance_plan_id"],
            ),
        )


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_linked_and_unlinked_records_can_be_acted_on_without_business_changes(prepared, action):
    db, _, saved = prepared
    boundary = MaintenanceRecordCreateApproval(db, EventLogger(stream=io.StringIO()))
    args = (saved.snapshot.snapshot_hash,) if action == "approve" else ()
    result = getattr(boundary, action)(identity(user="approver"), str(saved.approval_id), *args)
    state = "APPROVED" if action == "approve" else "REJECTED"
    assert result["status"] == result["approval_status"] == state
    assert current(db, saved)["canonical_snapshot"] == saved.snapshot.data
    if action == "approve":
        assert result["expires_at"] - result["approved_at"] == timedelta(minutes=30)
    else:
        assert result["approved_at"] is result["expires_at"] is None
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM maintenance_record").fetchone()["n"] == 0
        )
        assert (
            connection.execute("SELECT plan_status,version FROM maintenance_plan").fetchall()
            == [{"plan_status": "PLANNED", "version": 5}] * 2
        )
        assert (
            connection.execute("SELECT state_code FROM equipment_current_state").fetchall()
            == [{"state_code": "RUNNING"}] * 2
        )
        audit = connection.execute(
            "SELECT * FROM update_audit_event WHERE action=%s", (action.upper(),)
        ).fetchone()
        assert audit["details"] == {"target_count": 2}
    with pytest.raises(ProposalError) as caught:
        getattr(boundary, action)(identity(user="approver"), str(saved.approval_id), *args)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    assert current(db, saved)["expires_at"] == result["expires_at"]


@pytest.mark.parametrize("id_conflict", [False, True])
def test_id_or_business_key_collision_invalidates_all_without_record_inserts(prepared, id_conflict):
    db, _, saved = prepared
    insert_conflict(db, saved, id_conflict)
    stream = io.StringIO()
    with pytest.raises(ProposalError) as caught:
        approve(db, saved, stream=stream)
    assert caught.value.code == "CREATE_CONFLICT" and caught.value.transition_committed
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM maintenance_record").fetchone()["n"] == 1
        )
        assert connection.execute(
            "SELECT action,result_code FROM update_audit_event WHERE action!='PREPARE'"
        ).fetchall() == [{"action": "INVALIDATE", "result_code": "CREATE_CONFLICT"}]
    event = json.loads(stream.getvalue())
    assert event["result_code"] == "CREATE_CONFLICT" and event["after_status"] == "INVALIDATED"


@pytest.mark.parametrize(
    "actor,allowed",
    [
        (identity("floor", "other"), False),
        (identity("production", "other"), False),
        (identity(), False),
        (identity(user="other"), True),
        (identity("manager", "maintenance1"), True),
    ],
)
def test_roles_and_manager_only_self_approval(prepared, actor, allowed):
    db, _, saved = prepared
    if allowed:
        assert approve(db, saved, actor=actor)["status"] == "APPROVED"
    else:
        with pytest.raises(ProposalError) as caught:
            approve(db, saved, actor=actor)
        assert caught.value.code == "AUTHORIZATION_DENIED"
        assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_hash_mismatch_does_not_invalidate_pending_records(prepared):
    db, _, saved = prepared
    insert_conflict(db, saved, False)
    with pytest.raises(ProposalError) as caught:
        approve(db, saved, snapshot_hash="0" * 64)
    assert caught.value.code == "APPROVAL_MISMATCH"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("conflict", [False, True])
def test_audit_failure_rolls_back_transition_then_retry_succeeds(prepared, conflict):
    db, _, saved = prepared
    if conflict:
        insert_conflict(db, saved, False)
    with db.transaction() as connection:
        connection.execute("""CREATE FUNCTION fail_record_approval() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action IN ('APPROVE','INVALIDATE') THEN RAISE EXCEPTION 'private-secret'; END IF;
            RETURN NEW; END $$""")
        connection.execute(
            "CREATE TRIGGER fail_record_approval BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_record_approval()"
        )
    stream = io.StringIO()
    with pytest.raises(ProposalError) as caught:
        approve(db, saved, stream=stream)
    assert caught.value.code == "INTERNAL_ERROR"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
    assert "private-secret" not in str(caught.value) and "private-secret" not in stream.getvalue()
    with db.transaction() as connection:
        connection.execute("DROP TRIGGER fail_record_approval ON update_audit_event")
    if conflict:
        with pytest.raises(ProposalError) as caught:
            approve(db, saved)
        assert caught.value.code == "CREATE_CONFLICT"
    else:
        assert approve(db, saved)["status"] == "APPROVED"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_record_http_approval_and_rejection_are_supported(prepared, action):
    db, _, saved = prepared
    with client_for(db) as client:
        result = act(client, saved, action)
        assert result.status_code == 200
    assert current(db, saved)["status"] == ("APPROVED" if action == "approve" else "REJECTED")


def test_mixed_plan_and_record_request_stays_outside_scope(prepared):
    db, service, _ = prepared
    saved = prepare(service)
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_parallel_record_approval_has_one_winner(prepared):
    db, _, saved = prepared

    def attempt(_):
        try:
            return approve(db, saved)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["APPROVED", "INVALID_UPDATE_STATE"]
