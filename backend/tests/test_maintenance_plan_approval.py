from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from test_maintenance_prepare import identity, prepare, update
from test_maintenance_prepare import service as maintenance_fixture

from linescope.approvals import EquipmentApproval, MaintenancePlanUpdateApproval
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def prepared(db):
    db, svc = maintenance_fixture.__wrapped__(db)
    saved = prepare(svc, [update(), update(21)])
    return db, svc, saved


def approve(db, saved, actor=None):
    return MaintenancePlanUpdateApproval(db).approve(
        actor or identity(user="approver"), str(saved.approval_id), saved.snapshot.snapshot_hash
    )


def test_approval_checks_all_plans_and_does_not_change_business_data(prepared):
    db, _, saved = prepared
    result = approve(db, saved)
    assert result["status"] == "APPROVED"
    assert result["expires_at"] - result["approved_at"] == timedelta(minutes=30)
    with db.transaction() as c:
        assert (
            c.execute("SELECT plan_status,version FROM maintenance_plan").fetchall()
            == [{"plan_status": "PLANNED", "version": 5}] * 2
        )
        audit = c.execute("SELECT * FROM update_audit_event WHERE action='APPROVE'").fetchone()
        assert audit["details"] == {"target_count": 2}
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "INVALID_UPDATE_STATE"


def test_one_plan_conflict_invalidates_entire_request(prepared):
    db, _, saved = prepared
    with db.transaction() as c:
        c.execute(
            "UPDATE maintenance_plan SET version=6 WHERE maintenance_plan_id=%s", (UUID(int=21),)
        )
    with pytest.raises(ProposalError) as caught:
        approve(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    current = ProposalStore(db).get(identity(), str(saved.update_request_id))
    assert current["status"] == current["approval_status"] == "INVALIDATED"


@pytest.mark.parametrize(
    "actor,expected",
    [
        (identity("floor", "other"), 403),
        (identity("production", "other"), 403),
        (identity(user="maintenance1"), 403),
        (identity("manager", "maintenance1"), 200),
    ],
)
def test_maintenance_roles_and_self_approval(prepared, actor, expected):
    db, _, saved = prepared
    if expected == 200:
        assert approve(db, saved, actor)["status"] == "APPROVED"
    else:
        with pytest.raises(ProposalError) as caught:
            approve(db, saved, actor)
        assert caught.value.code == "AUTHORIZATION_DENIED"


def test_equipment_entrypoint_does_not_admit_maintenance(prepared):
    db, _, saved = prepared
    with pytest.raises(ProposalError) as caught:
        EquipmentApproval(db).approve(
            identity(user="approver"), str(saved.approval_id), saved.snapshot.snapshot_hash
        )
    assert caught.value.code == "INVALID_ARGUMENT"


def test_composite_create_record_request_stays_outside_update_scope(prepared):
    db, svc, _ = prepared
    saved = prepare(svc)
    for action in ("approve", "reject"):
        args = (saved.snapshot.snapshot_hash,) if action == "approve" else ()
        with pytest.raises(ProposalError) as caught:
            getattr(MaintenancePlanUpdateApproval(db), action)(
                identity(user="approver"), str(saved.approval_id), *args
            )
        assert caught.value.code == "INVALID_ARGUMENT"
    assert (
        ProposalStore(db).get(identity(), str(saved.update_request_id))["status"]
        == "WAITING_APPROVAL"
    )


def test_reject_maintenance_update_uses_shared_atomic_audit(prepared):
    db, _, saved = prepared
    assert (
        MaintenancePlanUpdateApproval(db).reject(identity(user="approver"), str(saved.approval_id))[
            "status"
        ]
        == "REJECTED"
    )
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='REJECT'"
            ).fetchone()["n"]
            == 1
        )


def test_parallel_maintenance_approvals_have_one_winner(prepared):
    db, _, saved = prepared

    def attempt(_):
        try:
            return approve(db, saved)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["APPROVED", "INVALID_UPDATE_STATE"]
