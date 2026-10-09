"""New Execute admission only; no persistence, replay, clock or state mutation.

Approval facts and now must come from the trusted server after row locks.
The transaction must recheck the deadline immediately before consumption,
revalidate current targets, and invalidate/expire in a separate transaction.
COMPLETED replay requires its own owner/result path before this admission.
"""

import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .approval_policy import APPROVAL_ROLES
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, SavedProposal
from .snapshot import CATEGORIES, CanonicalSnapshot


@dataclass(frozen=True)
class ApprovalFacts:
    approver_id: str
    current_approver_role: str | None
    snapshot_hash: str
    approved_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


def validate_new_execute(context, proposal, approval, *, now):
    """Return category for an authorized new execution, without changing state."""
    if not isinstance(context, ExecutionContext):
        raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
    if not isinstance(proposal, SavedProposal) or not isinstance(approval, ApprovalFacts):
        raise ProposalError("INTERNAL_ERROR", "Validated proposal and Approval facts are required")
    try:
        snapshot = CanonicalSnapshot(
            proposal.snapshot.canonical_text, proposal.snapshot.snapshot_hash
        )
        payload = snapshot.data
        category = CATEGORIES[payload["targets"][0]["target_type"]]
    except (ValueError, KeyError, AttributeError) as error:
        raise ProposalError("INTERNAL_ERROR", "Stored Snapshot is invalid") from error
    if context.authenticated_user_id != payload["requester_id"]:
        raise ProposalError("AUTHORIZATION_DENIED", "Only the original requester may execute")
    if (proposal.status, proposal.approval_status) != ("APPROVED", "APPROVED"):
        raise ProposalError("INVALID_UPDATE_STATE", "A new execution requires approved states")
    if approval.consumed_at is not None:
        raise ProposalError("APPROVAL_ALREADY_CONSUMED", "Approval has already been consumed")
    if (
        context.role not in REQUEST_ROLES[category]
        or type(approval.current_approver_role) is not str
        or approval.current_approver_role not in APPROVAL_ROLES[category]
    ):
        raise ProposalError("APPROVAL_INVALIDATED", "Required current permission has been lost")
    if approval.approver_id == payload["requester_id"] and (
        category == "DEPENDENCY" or approval.current_approver_role != "manager"
    ):
        raise ProposalError("APPROVAL_INVALIDATED", "Self approval is no longer permitted")
    if type(approval.approver_id) is not str or not approval.approver_id.strip():
        raise ProposalError("INTERNAL_ERROR", "Stored approver is invalid")
    if (
        type(approval.snapshot_hash) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", approval.snapshot_hash)
        or not hmac.compare_digest(approval.snapshot_hash, snapshot.snapshot_hash)
    ):
        raise ProposalError("APPROVAL_INVALIDATED", "Stored Approval hash does not match")
    times = (approval.approved_at, approval.expires_at, now)
    if any(not isinstance(value, datetime) or value.utcoffset() is None for value in times):
        raise ProposalError("INTERNAL_ERROR", "Server timestamps must be timezone aware")
    if (
        approval.expires_at - approval.approved_at != timedelta(minutes=30)
        or now < approval.approved_at
    ):
        raise ProposalError("INTERNAL_ERROR", "Stored Approval timestamps are inconsistent")
    if now >= approval.expires_at:
        raise ProposalError("APPROVAL_EXPIRED", "Approval deadline has been reached")
    return category
