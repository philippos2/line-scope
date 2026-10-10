"""Schedule-only production approval never updates operations or assignments."""

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from test_production_prepare import identity, prepare, target
from test_production_prepare import service as production_fixture

from linescope.approvals import ProductionScheduleApproval
from linescope.logging import EventLogger
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def world(db):
    db, service = production_fixture.__wrapped__(db)
    return db, service, prepare(service, [target(21), target(20)])


def current(db, saved):
    return ProposalStore(db).get(identity(), str(saved.update_request_id))


def action(db, saved, name="approve", actor=None, snapshot_hash=None):
    service = ProductionScheduleApproval(db, EventLogger(stream=io.StringIO()))
    args = [actor or identity(user="approver"), str(saved.approval_id)]
    if name == "approve":
        args.append(snapshot_hash or saved.snapshot.snapshot_hash)
    return getattr(service, name)(*args)


def business(db):
    with db.transaction() as c:
        return c.execute(
            "SELECT (SELECT jsonb_agg(to_jsonb(p) ORDER BY production_operation_id) FROM production_operation p) AS operations,(SELECT jsonb_agg(to_jsonb(a) ORDER BY assignment_id) FROM production_operation_equipment_assignment a) AS assignments"
        ).fetchone()


@pytest.mark.parametrize("name", ["approve", "reject"])
def test_all_schedules_share_one_human_decision_without_business_changes(world, name):
    db, _, saved = world
    before = business(db)
    result = action(db, saved, name)
    assert (
        result["status"]
        == result["approval_status"]
        == ("APPROVED" if name == "approve" else "REJECTED")
    )
    assert current(db, saved)["canonical_snapshot"] == saved.snapshot.data
    if name == "approve":
        assert result["expires_at"] - result["approved_at"] == timedelta(minutes=30)
    else:
        assert result["approved_at"] is result["expires_at"] is None
    with pytest.raises(ProposalError) as caught:
        action(db, saved, name)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    assert current(db, saved)["expires_at"] == result["expires_at"]
    assert business(db) == before
    with db.transaction() as c:
        assert c.execute(
            "SELECT details FROM update_audit_event WHERE action=%s", (name.upper(),)
        ).fetchone()["details"] == {"target_count": 2}


@pytest.mark.parametrize(
    "fault", ["version", "missing", "status_without_version", "active_without_version"]
)
def test_one_changed_schedule_invalidates_all_targets(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        queries = {
            "version": "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
            "missing": "DELETE FROM production_operation WHERE production_operation_id=%s",
            "status_without_version": "UPDATE production_operation SET planned_status='CANCELLED' WHERE production_operation_id=%s",
            "active_without_version": "UPDATE production_operation SET active=false WHERE production_operation_id=%s",
        }
        c.execute(queries[fault], (UUID(int=21),))
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "VERSION_CONFLICT" and caught.value.transition_committed
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert business(db) == before
    with db.transaction() as c:
        assert c.execute(
            "SELECT action,result_code FROM update_audit_event WHERE action!='PREPARE'"
        ).fetchall() == [{"action": "INVALIDATE", "result_code": "VERSION_CONFLICT"}]


@pytest.mark.parametrize(
    "actor,allowed",
    [
        (identity("floor", "other"), False),
        (identity("maintenance", "other"), False),
        (identity(), False),
        (identity(user="other"), True),
        (identity("manager", "production1"), True),
    ],
)
def test_production_roles_and_manager_only_self_approval(world, actor, allowed):
    db, _, saved = world
    if allowed:
        assert action(db, saved, actor=actor)["status"] == "APPROVED"
    else:
        with pytest.raises(ProposalError) as caught:
            action(db, saved, actor=actor)
        assert caught.value.code == "AUTHORIZATION_DENIED"
        assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_wrong_hash_keeps_pending_schedule(world):
    db, _, saved = world
    with pytest.raises(ProposalError) as caught:
        action(db, saved, snapshot_hash="0" * 64)
    assert caught.value.code == "APPROVAL_MISMATCH"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("conflict", [False, True])
def test_audit_failure_rolls_back_decision_then_retry_succeeds(world, conflict):
    db, _, saved = world
    with db.transaction() as c:
        if conflict:
            c.execute(
                "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
                (UUID(int=21),),
            )
        c.execute(
            """CREATE FUNCTION fail_schedule_approval() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action IN ('APPROVE','INVALIDATE') THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW; END $$"""
        )
        c.execute(
            "CREATE TRIGGER fail_schedule_approval BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_schedule_approval()"
        )
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
    with db.transaction() as c:
        c.execute("DROP TRIGGER fail_schedule_approval ON update_audit_event")
    if conflict:
        with pytest.raises(ProposalError) as caught:
            action(db, saved)
        assert caught.value.code == "VERSION_CONFLICT"
    else:
        assert action(db, saved)["status"] == "APPROVED"


def test_parallel_approval_has_one_winner(world):
    db, _, saved = world

    def run(_):
        try:
            return action(db, saved)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, range(2))) == ["APPROVED", "INVALID_UPDATE_STATE"]


def test_assignment_aware_request_remains_outside_schedule_scope(db):
    from test_production_assignment_prepare import prepare as prepare_assignments
    from test_production_assignment_prepare import service as assignment_fixture

    db, service = assignment_fixture.__wrapped__(db)
    saved = prepare_assignments(service)
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
