"""Assignment-aware human decisions leave all production/Graph business data unchanged."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb
from test_production_assignment_prepare import END, START, prepare, target
from test_production_assignment_prepare import service as production_fixture
from test_production_prepare import identity
from test_production_schedule_approval import business, current

from linescope.approvals import HumanApproval, ProductionAssignmentApproval
from linescope.logging import EventLogger
from linescope.proposals import ProposalError


@pytest.fixture
def world(db):
    db, service = production_fixture.__wrapped__(db)
    return db, service, prepare(service, [target(20), target(21, equipment=(102,))])


def action(db, saved, name="approve", actor=None, snapshot_hash=None):
    service = ProductionAssignmentApproval(db, EventLogger(stream=io.StringIO()))
    args = [actor or identity(user="approver"), str(saved.approval_id)]
    if name == "approve":
        args.append(snapshot_hash or saved.snapshot.snapshot_hash)
    return getattr(service, name)(*args)


def assert_unchanged(db, before):
    assert business(db) == before
    with db.transaction() as c:
        for table in ("business_update_history", "graph_outbox"):
            assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


@pytest.mark.parametrize("name", ["approve", "reject"])
def test_one_decision_for_two_parents_and_all_assignment_diffs(world, name):
    from datetime import timedelta

    db, _, saved = world
    before = business(db)
    result = action(db, saved, name)
    expected = "APPROVED" if name == "approve" else "REJECTED"
    assert result["status"] == result["approval_status"] == expected
    assert current(db, saved)["canonical_snapshot"] == saved.snapshot.data
    if name == "approve":
        assert result["expires_at"] - result["approved_at"] == timedelta(minutes=30)
    with pytest.raises(ProposalError) as caught:
        action(db, saved, name)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    assert current(db, saved)["expires_at"] == result["expires_at"]
    assert_unchanged(db, before)
    with db.transaction() as c:
        assert c.execute(
            "SELECT details FROM update_audit_event WHERE action=%s", (name.upper(),)
        ).fetchone()["details"] == {"target_count": 8}


@pytest.mark.parametrize("fault", ["version", "missing", "value", "active"])
def test_one_changed_parent_invalidates_every_target(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        if fault == "missing":
            c.execute(
                "DELETE FROM production_operation_equipment_assignment WHERE production_operation_id=%s",
                (UUID(int=21),),
            )
        c.execute(
            {
                "version": "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
                "missing": "DELETE FROM production_operation WHERE production_operation_id=%s",
                "value": "UPDATE production_operation SET planned_status='CANCELLED' WHERE production_operation_id=%s",
                "active": "UPDATE production_operation SET active=false WHERE production_operation_id=%s",
            }[fault],
            (UUID(int=21),),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "VERSION_CONFLICT" and caught.value.transition_committed
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert_unchanged(db, before)


@pytest.mark.parametrize("fault", ["version", "missing", "value", "deactivated", "added"])
def test_active_collection_change_without_parent_version_is_detected(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        if fault == "added":
            c.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,1)",
                (UUID(int=900), UUID(int=21), UUID(int=101), START),
            )
        else:
            c.execute(
                {
                    "version": "UPDATE production_operation_equipment_assignment SET version=5 WHERE assignment_id=%s",
                    "missing": "DELETE FROM production_operation_equipment_assignment WHERE assignment_id=%s",
                    "value": "UPDATE production_operation_equipment_assignment SET effective_to=%s WHERE assignment_id=%s",
                    "deactivated": "UPDATE production_operation_equipment_assignment SET active=false WHERE assignment_id=%s",
                }[fault],
                (END, UUID(int=31)) if fault == "value" else (UUID(int=31),),
            )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert_unchanged(db, before)


@pytest.mark.parametrize("fault", ["version", "missing", "value"])
def test_reused_inactive_assignment_is_also_revalidated(db, fault):
    db, service = production_fixture.__wrapped__(db)
    with db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,%s,false,9)",
            (UUID(int=40), UUID(int=20), UUID(int=101), START, END),
        )
    saved = prepare(service)
    with db.transaction() as c:
        c.execute(
            {
                "version": "UPDATE production_operation_equipment_assignment SET version=10 WHERE assignment_id=%s",
                "missing": "DELETE FROM production_operation_equipment_assignment WHERE assignment_id=%s",
                "value": "UPDATE production_operation_equipment_assignment SET effective_to=NULL WHERE assignment_id=%s",
            }[fault],
            (UUID(int=40),),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert_unchanged(db, before)


@pytest.mark.parametrize("fault", ["id", "key"])
def test_create_identity_or_inactive_business_key_collision(world, fault):
    db, _, saved = world
    child = next(t for t in saved.snapshot.data["targets"] if t["operation_type"] == "CREATE")
    state = {**child["after"], "active": False, "created_at": START, "updated_at": START}
    if fault == "id":
        state["effective_from"] = END
        state["effective_to"] = None
        state["equipment_id"] = str(UUID(int=100))
    else:
        state["assignment_id"] = str(UUID(int=900))
    with db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment SELECT (jsonb_populate_record(NULL::production_operation_equipment_assignment,%s)).*",
            (Jsonb(state),),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "CREATE_CONFLICT" and caught.value.transition_committed
    assert current(db, saved)["status"] == "INVALIDATED"
    assert_unchanged(db, before)


def test_schedule_and_assignment_parents_share_one_approval(db):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare(
        service,
        [
            target(21),
            {
                "production_operation_id": str(UUID(int=20)),
                "patch": {"planned_status": "CANCELLED"},
            },
        ],
    )
    before = business(db)
    assert action(db, saved)["status"] == "APPROVED"
    assert_unchanged(db, before)


@pytest.mark.parametrize("changed", [False, True])
def test_assignment_noop_with_schedule_patch_still_checks_fixed_collection(db, changed):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare(
        service, [target(equipment=(100,), end=None, patch={"planned_status": "CANCELLED"})]
    )
    assert len(saved.snapshot.data["targets"]) == 1
    if changed:
        with db.transaction() as c:
            c.execute(
                "UPDATE production_operation_equipment_assignment SET version=5 WHERE assignment_id=%s",
                (UUID(int=30),),
            )
        with pytest.raises(ProposalError) as caught:
            action(db, saved)
        assert caught.value.code == "VERSION_CONFLICT"
    else:
        assert action(db, saved)["status"] == "APPROVED"


def test_unrelated_assignment_changes_do_not_invalidate(db):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare(service)
    with db.transaction() as c:
        c.execute(
            "UPDATE production_operation_equipment_assignment SET version=5 WHERE assignment_id=%s",
            (UUID(int=31),),
        )
        c.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,false,1)",
            (UUID(int=900), UUID(int=20), UUID(int=102), START),
        )
    before = business(db)
    assert action(db, saved)["status"] == "APPROVED"
    assert_unchanged(db, before)


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
def test_current_role_and_production_self_approval_rules(world, actor, allowed):
    db, _, saved = world
    if allowed:
        assert action(db, saved, actor=actor)["status"] == "APPROVED"
    else:
        with pytest.raises(ProposalError) as caught:
            action(db, saved, actor=actor)
        assert caught.value.code == "AUTHORIZATION_DENIED"
        assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_wrong_hash_keeps_request_pending(world):
    db, _, saved = world
    with pytest.raises(ProposalError) as caught:
        action(db, saved, snapshot_hash="0" * 64)
    assert caught.value.code == "APPROVAL_MISMATCH"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("name", ["approve", "reject", "invalidate"])
def test_audit_failure_rolls_back_decision_and_retry_works(world, name):
    db, _, saved = world
    with db.transaction() as c:
        if name == "invalidate":
            c.execute(
                "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
                (UUID(int=21),),
            )
        c.execute(
            "CREATE FUNCTION fail_assignment_decision() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action IN ('APPROVE','REJECT','INVALIDATE') THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW; END $$"
        )
        c.execute(
            "CREATE TRIGGER fail_assignment_decision BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_assignment_decision()"
        )
    before = business(db)
    decision = "approve" if name == "invalidate" else name
    with pytest.raises(ProposalError) as caught:
        action(db, saved, decision)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert (
        current(db, saved)["status"] == "WAITING_APPROVAL"
        and current(db, saved)["approval_status"] == "PENDING"
    )
    assert_unchanged(db, before)
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action IN ('APPROVE','REJECT','INVALIDATE')"
            ).fetchone()["n"]
            == 0
        )
        c.execute("DROP TRIGGER fail_assignment_decision ON update_audit_event")
    if name == "invalidate":
        with pytest.raises(ProposalError) as caught:
            action(db, saved)
        assert caught.value.code == "VERSION_CONFLICT"
    else:
        assert action(db, saved, decision)["status"] == (
            "APPROVED" if name == "approve" else "REJECTED"
        )


def test_concurrent_approve_and_reject_have_one_winner(world):
    db, _, saved = world
    barrier = Barrier(2)

    def run(name):
        barrier.wait(timeout=5)
        try:
            return action(db, saved, name)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, ("approve", "reject")))
    assert results.count("INVALID_UPDATE_STATE") == 1
    winner = next(r for r in results if r != "INVALID_UPDATE_STATE")
    assert winner in {"APPROVED", "REJECTED"}
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == winner
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action IN ('APPROVE','REJECT')"
            ).fetchone()["n"]
            == 1
        )


def test_public_router_remains_closed_until_assignment_execute_is_ready(world):
    db, _, saved = world
    with pytest.raises(ProposalError) as caught:
        HumanApproval(db, EventLogger(stream=io.StringIO())).approve(
            identity(user="approver"), str(saved.approval_id), saved.snapshot.snapshot_hash
        )
    assert caught.value.code == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize("variant", ["shorten", "reuse"])
def test_assignment_update_diffs_can_be_approved_without_business_changes(db, variant):
    db, service = production_fixture.__wrapped__(db)
    if variant == "reuse":
        with db.transaction() as c:
            c.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,%s,false,9)",
                (UUID(int=40), UUID(int=20), UUID(int=101), START, END),
            )
        saved = prepare(service)
    else:
        from test_production_assignment_prepare import NEW_END

        saved = prepare(service, [target(start=END, end=NEW_END)])
    assert any(
        t["target_type"] == "ProductionOperationEquipmentAssignment"
        and t["operation_type"] == "UPDATE"
        for t in saved.snapshot.data["targets"]
    )
    before = business(db)
    assert action(db, saved)["status"] == "APPROVED"
    assert_unchanged(db, before)


def test_create_id_collision_with_another_operations_inactive_row(db):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare(service)
    child = next(t for t in saved.snapshot.data["targets"] if t["operation_type"] == "CREATE")
    with db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,%s,false,1)",
            (child["target_id"], UUID(int=21), UUID(int=102), START, END),
        )
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "CREATE_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"


def test_schedule_only_request_stays_outside_internal_assignment_scope(db):
    from test_production_prepare import prepare as schedule_prepare
    from test_production_prepare import target as schedule_target

    db, service = production_fixture.__wrapped__(db)
    saved = schedule_prepare(service, [schedule_target()])
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
