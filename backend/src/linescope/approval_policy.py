"""Human approval admission only; persistence and current-state checks are separate.

Successful validation does not approve a request. The future transaction must
lock Request then Approval, revalidate stored Targets/current versions, persist
the transition and its audit atomically, and obtain time from the server.
"""

import hmac
import re

from .execution import ExecutionContext
from .proposals import ProposalError, SavedProposal
from .snapshot import CATEGORIES, CanonicalSnapshot

APPROVAL_ROLES = {
    "EQUIPMENT_STATE": {"maintenance", "manager"},
    "MAINTENANCE": {"maintenance", "manager"},
    "PRODUCTION_OPERATION": {"production", "manager"},
    "DEPENDENCY": {"manager"},
}


def validate_approve(context, proposal, snapshot_hash):
    """Return the authorized category, without changing any state or deadline."""
    if not isinstance(context, ExecutionContext):
        raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
    if not isinstance(proposal, SavedProposal) or not isinstance(
        proposal.snapshot, CanonicalSnapshot
    ):
        raise ProposalError("INTERNAL_ERROR", "A validated saved proposal is required")
    try:
        verified = CanonicalSnapshot(
            proposal.snapshot.canonical_text, proposal.snapshot.snapshot_hash
        )
        payload = verified.data
        categories = {CATEGORIES[target["target_type"]] for target in payload["targets"]}
        if len(categories) != 1:
            raise ValueError("One category is required")
    except (ValueError, KeyError) as error:
        raise ProposalError("INTERNAL_ERROR", "Stored Snapshot is invalid") from error
    category = next(iter(categories))
    if context.role not in APPROVAL_ROLES[category]:
        raise ProposalError("AUTHORIZATION_DENIED", "Approval permission is required")
    if context.authenticated_user_id == payload["requester_id"] and (
        category == "DEPENDENCY" or context.role != "manager"
    ):
        raise ProposalError("AUTHORIZATION_DENIED", "Self approval is not permitted")
    if (proposal.status, proposal.approval_status) != ("WAITING_APPROVAL", "PENDING"):
        raise ProposalError("INVALID_UPDATE_STATE", "Only pending requests may be approved")
    if type(snapshot_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_hash):
        raise ProposalError("INVALID_ARGUMENT", "A canonical Snapshot hash is required")
    if not hmac.compare_digest(snapshot_hash, verified.snapshot_hash):
        raise ProposalError("APPROVAL_MISMATCH", "Submitted Snapshot hash does not match")
    return category
