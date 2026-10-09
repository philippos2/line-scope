from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from test_approvals import approve
from test_approvals import prepared as equipment_prepared
from test_proposals import context

from linescope.approvals import EquipmentApproval
from linescope.database import Database
from linescope.demo_seed import DEMO_EQUIPMENT
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def prepared(db):
    return equipment_prepared.__wrapped__(db)


def reject(db, saved, actor=None):
    return EquipmentApproval(db).reject(
        actor or context("approver", "maintenance"), str(saved.approval_id)
    )


def test_reject_saves_both_states_and_audit_without_changing_business_data(prepared):
    db, saved = prepared
    assert reject(db, saved)["status"] == "REJECTED"
    result = ProposalStore(db).get(context("requester"), str(saved.update_request_id))
    assert result["status"] == result["approval_status"] == "REJECTED"
    assert result["approved_at"] is None and result["expires_at"] is None
    with db.transaction() as c:
        event = c.execute("SELECT * FROM update_audit_event WHERE action='REJECT'").fetchone()
        assert event["actor_id"] == "approver" and event["result_code"] == "OK"
        assert event["before_status"] == "WAITING_APPROVAL"
        assert event["after_status"] == "REJECTED"
        assert (
            c.execute(
                "SELECT state_code FROM equipment_current_state WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            ).fetchone()["state_code"]
            == "STOPPED"
        )
    for operation in (reject, approve):
        with pytest.raises(ProposalError) as caught:
            operation(db, saved)
        assert caught.value.code == "INVALID_UPDATE_STATE"


@pytest.mark.parametrize("actor", [context("requester", "maintenance"), context("other", "floor")])
def test_unauthorized_rejection_preserves_pending_state(prepared, actor):
    db, saved = prepared
    with pytest.raises(ProposalError) as caught:
        reject(db, saved, actor)
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "WAITING_APPROVAL"
    )


def test_manager_can_reject_own_equipment_request(prepared):
    db, saved = prepared
    assert reject(db, saved, context("requester", "manager"))["status"] == "REJECTED"


def test_rejection_cannot_cancel_approved_request(prepared):
    db, saved = prepared
    approved = approve(db, saved)
    with pytest.raises(ProposalError) as caught:
        reject(db, saved)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    result = ProposalStore(db).get(context("requester"), str(saved.update_request_id))
    assert result["status"] == "APPROVED" and result["expires_at"] == approved["expires_at"]


def test_rejection_audit_failure_rolls_back_both_states(prepared):
    db, saved = prepared
    with db.transaction() as c:
        c.execute("""CREATE FUNCTION reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private-secret'; END $$""")
        c.execute(
            "CREATE TRIGGER reject_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_audit()"
        )
    with pytest.raises(ProposalError) as caught:
        reject(db, saved)
    assert caught.value.code == "INTERNAL_ERROR"
    result = ProposalStore(db).get(context("requester"), str(saved.update_request_id))
    assert result["status"] == "WAITING_APPROVAL" and result["approval_status"] == "PENDING"


@pytest.mark.parametrize("other", [reject, approve])
def test_concurrent_reject_and_transition_have_one_winner(prepared, other):
    db, saved = prepared

    def attempt(operation):
        try:
            return operation(db, saved)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, [reject, other]))
    assert results.count("INVALID_UPDATE_STATE") == 1
    assert any(value in {"APPROVED", "REJECTED"} for value in results)
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action IN ('APPROVE','REJECT')"
            ).fetchone()["n"]
            == 1
        )


def test_rejection_lock_timeout_is_retryable(prepared):
    db, saved = prepared
    bounded = Database(replace(db.settings, lock_ms=50))
    with db.transaction() as c:
        c.execute(
            "SELECT update_request_id FROM update_request WHERE update_request_id=%s FOR UPDATE",
            (saved.update_request_id,),
        )
        with pytest.raises(ProposalError) as caught:
            reject(bounded, saved)
        assert caught.value.code == "RESOURCE_BUSY"
    assert reject(db, saved)["status"] == "REJECTED"
