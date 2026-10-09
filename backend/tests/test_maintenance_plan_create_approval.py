"""Plan CREATE approval observes uniqueness without inserting plans."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from test_maintenance_plan_approval_api import act, client_for
from test_maintenance_prepare import create_plan, create_record, identity, prepare, update
from test_maintenance_prepare import service as maintenance_fixture

from linescope.approvals import MaintenancePlanCreateApproval
from linescope.logging import EventLogger
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def prepared(db):
    db, service = maintenance_fixture.__wrapped__(db)
    saved = prepare(service, [create_plan("NEW-A"), create_plan("NEW-B")])
    return db, service, saved


def current(db, saved):
    return ProposalStore(db).get(identity(), str(saved.update_request_id))


def approve(db, saved, *, actor=None, snapshot_hash=None, stream=None):
    return MaintenancePlanCreateApproval(db, EventLogger(stream=stream or io.StringIO())).approve(
        actor or identity(user="approver"),
        str(saved.approval_id),
        snapshot_hash or saved.snapshot.snapshot_hash,
    )


def insert_conflict(db, saved, *, id_conflict=False):
    after = saved.snapshot.data["targets"][0]["after"]
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                after["maintenance_plan_id"] if id_conflict else uuid4(),
                "OTHER-CODE" if id_conflict else after["plan_code"],
                after["equipment_id"],
                after["planned_start"],
                after["planned_end"],
                after["plan_status"],
            ),
        )


def test_all_create_targets_are_approved_without_business_inserts(prepared):
    db, _, saved = prepared
    original = saved.snapshot
    result = approve(db, saved)
    assert result["status"] == result["approval_status"] == "APPROVED"
    assert result["expires_at"] - result["approved_at"] == timedelta(minutes=30)
    assert current(db, saved)["canonical_snapshot"] == original.data
    assert current(db, saved)["snapshot_hash"] == original.snapshot_hash
    assert all(t["before"] is t["expected_version"] is None for t in original.data["targets"])
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM maintenance_plan").fetchone()["n"] == 2
        audit = connection.execute(
            "SELECT * FROM update_audit_event WHERE action='APPROVE'"
        ).fetchone()
        assert audit["details"] == {"target_count": 2}
        assert (
            connection.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"]
            == 0
        )
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    assert current(db, saved)["expires_at"] == result["expires_at"]


@pytest.mark.parametrize("id_conflict", [False, True])
def test_post_prepare_id_or_business_key_collision_invalidates_all(prepared, id_conflict):
    db, _, saved = prepared
    insert_conflict(db, saved, id_conflict=id_conflict)
    stream = io.StringIO()
    with pytest.raises(ProposalError) as caught:
        approve(db, saved, stream=stream)
    assert caught.value.code == "CREATE_CONFLICT"
    assert caught.value.transition_committed
    state = current(db, saved)
    assert state["status"] == state["approval_status"] == "INVALIDATED"
    assert state["approved_at"] is state["expires_at"] is None
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM maintenance_plan").fetchone()["n"] == 3
        assert connection.execute(
            "SELECT action,result_code FROM update_audit_event WHERE action!='PREPARE'"
        ).fetchall() == [{"action": "INVALIDATE", "result_code": "CREATE_CONFLICT"}]
    event = json.loads(stream.getvalue())
    assert event["outcome"] == "rejected" and event["result_code"] == "CREATE_CONFLICT"
    assert event["before_status"] == "WAITING_APPROVAL" and event["after_status"] == "INVALIDATED"


def test_wrong_hash_does_not_invalidate_even_when_create_key_conflicts(prepared):
    db, _, saved = prepared
    insert_conflict(db, saved)
    with pytest.raises(ProposalError) as caught:
        approve(db, saved, snapshot_hash="0" * 64)
    assert caught.value.code == "APPROVAL_MISMATCH"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "actor,allowed",
    [
        (identity("floor", "other"), False),
        (identity("production", "other"), False),
        (identity(user="maintenance1"), False),
        (identity("maintenance", "other"), True),
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


def test_reject_pending_create_without_rechecking_uniqueness(prepared):
    db, _, saved = prepared
    insert_conflict(db, saved)
    result = MaintenancePlanCreateApproval(db, EventLogger(stream=io.StringIO())).reject(
        identity(user="approver"), str(saved.approval_id)
    )
    assert result["status"] == result["approval_status"] == "REJECTED"
    assert result["approved_at"] is result["expires_at"] is None
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM maintenance_plan").fetchone()["n"] == 3
        assert (
            connection.execute(
                "SELECT result_code FROM update_audit_event WHERE action='REJECT'"
            ).fetchone()["result_code"]
            == "OK"
        )


@pytest.mark.parametrize("kind", ["update", "record", "mixed"])
def test_other_operations_and_record_targets_stay_outside_scope(prepared, kind):
    db, service, _ = prepared
    saved = prepare(
        service,
        {
            "update": [update()],
            "record": [create_record()],
            "mixed": [create_plan("NEW-C"), update()],
        }[kind],
    )
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_create_http_approval_and_rejection_follow_the_saved_request(prepared, action):
    db, _, saved = prepared
    with client_for(db) as client:
        result = act(client, saved, action)
        assert result.status_code == 200
        assert result.json()["data"]["approval_id"] == str(saved.approval_id)
    assert current(db, saved)["status"] == ("APPROVED" if action == "approve" else "REJECTED")


@pytest.mark.parametrize("conflict", [False, True])
def test_transition_audit_failure_rolls_back_and_retry_preserves_correct_outcome(
    prepared, conflict
):
    db, _, saved = prepared
    if conflict:
        insert_conflict(db, saved)
    with db.transaction() as connection:
        connection.execute("""CREATE FUNCTION fail_create_approval_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action IN ('APPROVE','INVALIDATE') THEN RAISE EXCEPTION 'private-secret'; END IF;
            RETURN NEW; END $$""")
        connection.execute(
            "CREATE TRIGGER fail_create_approval_audit BEFORE INSERT ON update_audit_event "
            "FOR EACH ROW EXECUTE FUNCTION fail_create_approval_audit()"
        )
    stream = io.StringIO()
    with pytest.raises(ProposalError) as caught:
        approve(db, saved, stream=stream)
    assert caught.value.code == "INTERNAL_ERROR"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
    assert "private-secret" not in str(caught.value) and "private-secret" not in stream.getvalue()
    with db.transaction() as connection:
        connection.execute("DROP TRIGGER fail_create_approval_audit ON update_audit_event")
    if conflict:
        with pytest.raises(ProposalError) as caught:
            approve(db, saved)
        assert caught.value.code == "CREATE_CONFLICT"
        assert current(db, saved)["status"] == "INVALIDATED"
    else:
        assert approve(db, saved)["status"] == "APPROVED"


def test_parallel_approval_has_one_winner(prepared):
    db, _, saved = prepared

    def attempt(_):
        try:
            return approve(db, saved)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["APPROVED", "INVALID_UPDATE_STATE"]
