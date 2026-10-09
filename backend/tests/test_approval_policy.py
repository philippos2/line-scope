from dataclasses import replace
from uuid import uuid4

import pytest
from test_proposals import category_snapshot, context

from linescope.approval_policy import validate_approve
from linescope.proposals import ProposalError, SavedProposal


def proposal(category="equipment", owner="requester"):
    return SavedProposal(
        uuid4(),
        uuid4(),
        uuid4(),
        "WAITING_APPROVAL",
        "PENDING",
        "UPDATE",
        category_snapshot(category, context(owner, "manager")),
        False,
    )


@pytest.mark.parametrize("category", ["equipment", "maintenance", "production", "dependency"])
@pytest.mark.parametrize("role", ["floor", "maintenance", "production", "manager"])
@pytest.mark.parametrize("self_approval", [False, True])
def test_category_role_and_self_approval_matrix(category, role, self_approval):
    saved = proposal(category)
    actor = context("requester" if self_approval else "approver", role)
    allowed = (
        role == "manager"
        or (role == "maintenance" and category in {"equipment", "maintenance"})
        or (role == "production" and category == "production")
    ) and (not self_approval or (role == "manager" and category != "dependency"))
    if allowed:
        assert validate_approve(actor, saved, saved.snapshot.snapshot_hash) in {
            "EQUIPMENT_STATE",
            "MAINTENANCE",
            "PRODUCTION_OPERATION",
            "DEPENDENCY",
        }
    else:
        with pytest.raises(ProposalError) as caught:
            validate_approve(actor, saved, saved.snapshot.snapshot_hash)
        assert caught.value.code == "AUTHORIZATION_DENIED"


@pytest.mark.parametrize(
    "status,approval_status",
    [
        ("APPROVED", "APPROVED"),
        ("COMPLETED", "CONSUMED"),
        ("REJECTED", "REJECTED"),
        ("INVALIDATED", "INVALIDATED"),
        ("EXPIRED", "EXPIRED"),
        ("FAILED", "INVALIDATED"),
    ],
)
def test_reapproval_and_terminal_states_are_rejected_without_mutation(status, approval_status):
    saved = replace(proposal(), status=status, approval_status=approval_status)
    with pytest.raises(ProposalError) as caught:
        validate_approve(context("approver", "manager"), saved, saved.snapshot.snapshot_hash)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    assert saved.status == status and saved.approval_status == approval_status


@pytest.mark.parametrize("value", [None, 1, "ABC", "F" * 64, "0" * 63])
def test_malformed_hash_is_invalid_argument(value):
    with pytest.raises(ProposalError) as caught:
        validate_approve(context("approver", "manager"), proposal(), value)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_mismatched_hash_does_not_change_pending_state():
    saved = proposal()
    with pytest.raises(ProposalError) as caught:
        validate_approve(context("approver", "manager"), saved, "0" * 64)
    assert caught.value.code == "APPROVAL_MISMATCH"
    assert (saved.status, saved.approval_status) == ("WAITING_APPROVAL", "PENDING")


def test_identity_cannot_be_supplied_by_dict():
    saved = proposal()
    with pytest.raises(ProposalError) as caught:
        validate_approve(
            {"role": "manager", "user_id": "approver"}, saved, saved.snapshot.snapshot_hash
        )
    assert caught.value.code == "AUTHENTICATION_REQUIRED"


def test_corrupted_stored_snapshot_is_not_accepted():
    saved = proposal()
    object.__setattr__(saved.snapshot, "canonical_text", "{}")
    with pytest.raises(ProposalError) as caught:
        validate_approve(context("approver", "manager"), saved, saved.snapshot.snapshot_hash)
    assert caught.value.code == "INTERNAL_ERROR"
