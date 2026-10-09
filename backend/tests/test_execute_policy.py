from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from test_approval_policy import proposal
from test_proposals import context

from linescope.execute_policy import ApprovalFacts, validate_new_execute
from linescope.proposals import ProposalError

NOW = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)


def approved(category="equipment", approver="approver", role="manager"):
    saved = replace(proposal(category), status="APPROVED", approval_status="APPROVED")
    facts = ApprovalFacts(
        approver, role, saved.snapshot.snapshot_hash, NOW, NOW + timedelta(minutes=30)
    )
    return saved, facts


def assert_code(code, actor, saved, facts, now=NOW):
    with pytest.raises(ProposalError) as caught:
        validate_new_execute(actor, saved, facts, now=now)
    assert caught.value.code == code
    assert saved.status == "APPROVED" or code == "INVALID_UPDATE_STATE"


@pytest.mark.parametrize("category", ["equipment", "maintenance", "production", "dependency"])
@pytest.mark.parametrize("role", ["floor", "maintenance", "production", "manager"])
def test_requester_current_role_matrix(category, role):
    saved, facts = approved(category)
    permitted = (
        role == "manager"
        or (category == "equipment" and role in {"floor", "maintenance"})
        or (category == "maintenance" and role == "maintenance")
        or (category == "production" and role == "production")
        or (category == "dependency" and role in {"maintenance", "production"})
    )
    if permitted:
        assert validate_new_execute(context("requester", role), saved, facts, now=NOW)
    else:
        assert_code("APPROVAL_INVALIDATED", context("requester", role), saved, facts)


@pytest.mark.parametrize("category", ["equipment", "maintenance", "production", "dependency"])
@pytest.mark.parametrize("role", [None, "floor", "maintenance", "production", "manager"])
def test_approver_current_role_matrix(category, role):
    saved, facts = approved(category, role=role)
    permitted = (
        role == "manager"
        or (category in {"equipment", "maintenance"} and role == "maintenance")
        or (category == "production" and role == "production")
    )
    if permitted:
        assert validate_new_execute(context("requester", "manager"), saved, facts, now=NOW)
    else:
        assert_code("APPROVAL_INVALIDATED", context("requester", "manager"), saved, facts)


@pytest.mark.parametrize("category", ["equipment", "maintenance", "production", "dependency"])
def test_manager_self_approval_except_dependency(category):
    saved, facts = approved(category, approver="requester")
    if category == "dependency":
        assert_code("APPROVAL_INVALIDATED", context("requester", "manager"), saved, facts)
    else:
        assert validate_new_execute(context("requester", "manager"), saved, facts, now=NOW)


@pytest.mark.parametrize(
    "offset,code",
    [
        (timedelta(minutes=30) - timedelta(microseconds=1), None),
        (timedelta(minutes=30), "APPROVAL_EXPIRED"),
        (timedelta(minutes=31), "APPROVAL_EXPIRED"),
    ],
)
def test_deadline_boundary(offset, code):
    saved, facts = approved()
    if code:
        assert_code(code, context("requester", "manager"), saved, facts, NOW + offset)
    else:
        assert validate_new_execute(context("requester", "manager"), saved, facts, now=NOW + offset)


@pytest.mark.parametrize("actor", [context("approver", "manager"), context("other", "manager")])
def test_nonowner_rejected_before_expiration(actor):
    saved, facts = approved()
    assert_code("AUTHORIZATION_DENIED", actor, saved, facts, NOW + timedelta(days=1))


@pytest.mark.parametrize(
    "status,approval_status",
    [
        ("WAITING_APPROVAL", "PENDING"),
        ("COMPLETED", "CONSUMED"),
        ("REJECTED", "REJECTED"),
        ("INVALIDATED", "INVALIDATED"),
        ("EXPIRED", "EXPIRED"),
    ],
)
def test_nonapproved_states_require_separate_path(status, approval_status):
    saved, facts = approved()
    assert_code(
        "INVALID_UPDATE_STATE",
        context("requester", "manager"),
        replace(saved, status=status, approval_status=approval_status),
        facts,
    )


def test_hash_and_consumption_and_timestamp_integrity():
    saved, facts = approved()
    actor = context("requester", "manager")
    for changes, code in [
        ({"snapshot_hash": "0" * 64}, "APPROVAL_INVALIDATED"),
        ({"consumed_at": NOW}, "APPROVAL_ALREADY_CONSUMED"),
        ({"expires_at": NOW + timedelta(minutes=31)}, "INTERNAL_ERROR"),
        ({"approved_at": NOW.replace(tzinfo=None)}, "INTERNAL_ERROR"),
        ({"approver_id": ""}, "INTERNAL_ERROR"),
    ]:
        assert_code(code, actor, saved, replace(facts, **changes))
    assert_code("INTERNAL_ERROR", actor, saved, facts, NOW - timedelta(microseconds=1))


def test_untrusted_identity_and_corrupt_snapshot_are_rejected():
    saved, facts = approved()
    assert_code(
        "AUTHENTICATION_REQUIRED", {"user_id": "requester", "role": "manager"}, saved, facts
    )
    object.__setattr__(saved.snapshot, "canonical_text", "{}")
    assert_code("INTERNAL_ERROR", context("requester", "manager"), saved, facts)


def test_self_approval_permission_loss_is_detected_even_if_category_role_remains():
    saved, facts = approved(approver="requester", role="maintenance")
    assert_code("APPROVAL_INVALIDATED", context("requester", "maintenance"), saved, facts)


def test_malformed_hash_is_rejected_without_comparison_exception():
    saved, facts = approved()
    assert_code(
        "APPROVAL_INVALIDATED",
        context("requester", "manager"),
        saved,
        replace(facts, snapshot_hash="秘密"),
    )
