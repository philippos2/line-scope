"""Internal proposal storage, not a Prepare Tool or an approval/execute API.

The trusted caller must read consistent current business rows, validate all
business constraints, and derive normalized Prepare/Agent input hashes before
saving. This repository writes only proposal metadata and pending approval.
Replacement saves invalidate the old request and approval in the same transaction.
"""

import hmac
import re
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg

from .audit import prepare_saved, proposal_replaced
from .canonical import canonical_json, normalize_uuid
from .core_proposals import (
    insert_pending_approval,
    insert_pending_request,
    insert_proposal_target,
    invalidate_replaced_approval,
    invalidate_replaced_request,
    lock_replaced_request,
    lock_request_approval,
)
from .execution import ExecutionContext
from .snapshot import CATEGORIES, CanonicalSnapshot

REQUEST_ROLES = {
    "EQUIPMENT_STATE": {"floor", "maintenance", "manager"},
    "MAINTENANCE": {"maintenance", "manager"},
    "PRODUCTION_OPERATION": {"production", "manager"},
    "DEPENDENCY": {"maintenance", "production", "manager"},
}
STATE_PAIRS = {
    ("WAITING_APPROVAL", "PENDING"),
    ("APPROVED", "APPROVED"),
    ("COMPLETED", "CONSUMED"),
    ("REJECTED", "REJECTED"),
    ("EXPIRED", "EXPIRED"),
    ("INVALIDATED", "INVALIDATED"),
    ("FAILED", "INVALIDATED"),
}

# One statement observes request, approval and every target together.
LOOKUP = """
SELECT r.*, a.approval_id, a.status AS approval_status,
       a.approved_at, a.expires_at,
       a.snapshot_hash AS approval_hash,
       (SELECT jsonb_agg(jsonb_build_object(
           'target_type',t.target_type,'target_id',t.target_id,
           'business_key',t.business_key,'operation_type',t.operation_type,
           'before',t.before_snapshot,'after',t.proposed_snapshot,
           'expected_version',t.expected_version
       ) ORDER BY t.target_type,t.target_id)
        FROM update_target t WHERE t.update_request_id=r.update_request_id) AS targets
FROM update_request r LEFT JOIN approval a USING(update_request_id)
WHERE r.requester_id=%s AND r.prepare_retry_key=%s
"""


def _effective_status(status, expires_at, observed_at):
    return (
        "EXPIRED"
        if status == "APPROVED" and expires_at is not None and observed_at >= expires_at
        else status
    )


class ProposalError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": {}}


@dataclass(frozen=True)
class SavedProposal:
    update_request_id: UUID
    approval_id: UUID
    idempotency_key: UUID
    status: str
    approval_status: str
    operation_type: str
    snapshot: CanonicalSnapshot
    replayed: bool


def _operation(targets):
    operations = {target["operation_type"] for target in targets}
    return next(iter(operations)) if len(operations) == 1 else "COMPOSITE"


def _arguments(context, retry_key, prepare_hash, agent_hash):
    if not isinstance(context, ExecutionContext):
        raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
    try:
        key = normalize_uuid(retry_key)
        if prepare_hash is None and agent_hash is None:
            raise ValueError("At least one input hash is required")
        for value in (prepare_hash, agent_hash):
            if value is not None and (
                type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value)
            ):
                raise ValueError("Invalid input hash")
        return key
    except ValueError as error:
        raise ProposalError("INVALID_ARGUMENT", "Invalid proposal retry arguments") from error


def _saved(row, prepare_hash, agent_hash, *, replayed):
    for field, provided in (("prepare_input_hash", prepare_hash), ("agent_input_hash", agent_hash)):
        if provided is not None and not hmac.compare_digest(row[field], provided):
            raise ProposalError("DUPLICATE_REQUEST", "Retry key was used for different input")
    try:
        snapshot = CanonicalSnapshot(row["canonical_snapshot"], row["snapshot_hash"])
        payload = snapshot.data
        rebuilt = {**payload, "targets": row["targets"]}
        # Constructor validates schema, category, ordering and duplicates too.
        CanonicalSnapshot(canonical_json(rebuilt), row["snapshot_hash"])
        if (
            row["approval_id"] is None
            or not hmac.compare_digest(row["approval_hash"], row["snapshot_hash"])
            or row["requester_id"] != payload["requester_id"]
            or row["snapshot_schema_version"] != payload["schema_version"]
            or row["operation_type"] != _operation(payload["targets"])
            or (row["status"], row["approval_status"]) not in STATE_PAIRS
        ):
            raise ValueError("Stored proposal metadata disagrees")
        return SavedProposal(
            row["update_request_id"],
            row["approval_id"],
            row["idempotency_key"],
            row["status"],
            row["approval_status"],
            row["operation_type"],
            snapshot,
            replayed,
        )
    except (ValueError, TypeError, KeyError) as error:
        raise ProposalError(
            "INTERNAL_ERROR", "Stored proposal failed integrity verification"
        ) from error


class ProposalStore:
    def __init__(self, database):
        self.database = database

    def get(self, context, request_id):
        """Read an immutable proposal under the history visibility boundary."""
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        try:
            request_id = normalize_uuid(request_id)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid update request ID") from error
        with self._transaction(read_only=True) as connection:
            row = connection.execute(
                LOOKUP.replace(
                    "SELECT r.*,", "SELECT statement_timestamp() AS observed_at, r.*,"
                ).replace(
                    "WHERE r.requester_id=%s AND r.prepare_retry_key=%s",
                    "WHERE r.update_request_id=%s",
                ),
                (request_id,),
            ).fetchone()
            if row is None:
                raise ProposalError("TARGET_NOT_FOUND", "Update request was not found")
            # Do not expose any stored content before authorizing the reader.
            allowed = {
                "floor": set(),
                "maintenance": {"EQUIPMENT_STATE", "MAINTENANCE"},
                "production": {"PRODUCTION_OPERATION"},
                "manager": set(REQUEST_ROLES),
            }[context.role]
            try:
                categories = {CATEGORIES[t["target_type"]] for t in row["targets"]}
                if len(categories) != 1:
                    raise ValueError("Invalid categories")
                category = next(iter(categories))
            except (KeyError, TypeError, ValueError) as error:
                raise ProposalError("INTERNAL_ERROR", "Stored categories are invalid") from error
            if row["requester_id"] != context.authenticated_user_id and category not in allowed:
                raise ProposalError("AUTHORIZATION_DENIED", "Update request visibility is required")
            saved = _saved(row, None, None, replayed=False)
            if CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]] != category:
                raise ProposalError("INTERNAL_ERROR", "Stored category disagrees with Snapshot")
            return {
                "update_request_id": saved.update_request_id,
                "approval_id": saved.approval_id,
                "status": saved.status,
                "effective_status": _effective_status(
                    saved.status, row["expires_at"], row["observed_at"]
                ),
                "approval_status": saved.approval_status,
                "canonical_snapshot": saved.snapshot.data,
                "snapshot_hash": saved.snapshot.snapshot_hash,
                "snapshot_schema_version": saved.snapshot.data["schema_version"],
                "prepare_retry_key": row["prepare_retry_key"],
                "approved_at": row["approved_at"],
                "expires_at": row["expires_at"],
                "execution_result": row["execution_result"],
            }

    @contextmanager
    def _transaction(self, *, read_only=False):
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY"
                    if read_only
                    else "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
                )
                yield connection
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as error:
            raise ProposalError("RESOURCE_BUSY", "Proposal storage is temporarily busy") from error
        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            raise ProposalError(
                "DEPENDENCY_UNAVAILABLE", "Proposal storage is unavailable"
            ) from error
        except psycopg.Error as error:
            raise ProposalError("INTERNAL_ERROR", "Proposal storage failed") from error

    def find_by_retry(self, context, retry_key, *, prepare_input_hash=None, agent_input_hash=None):
        """Owner-only early replay lookup; HTTP may compare only Agent input."""
        key = _arguments(context, retry_key, prepare_input_hash, agent_input_hash)
        with self._transaction(read_only=True) as connection:
            row = connection.execute(LOOKUP, (context.authenticated_user_id, key)).fetchone()
            return _saved(row, prepare_input_hash, agent_input_hash, replayed=True) if row else None

    def save(self, context, snapshot, retry_key, *, prepare_input_hash, agent_input_hash):
        """Save immutable proposal content and atomically invalidate a replaced proposal."""
        key = _arguments(context, retry_key, prepare_input_hash, agent_input_hash)
        if prepare_input_hash is None or agent_input_hash is None:
            raise ProposalError("INVALID_ARGUMENT", "Saving requires both input hashes")
        with self._transaction() as connection:
            row = connection.execute(LOOKUP, (context.authenticated_user_id, key)).fetchone()
            if row:
                return _saved(row, prepare_input_hash, agent_input_hash, replayed=True)
            if not isinstance(snapshot, CanonicalSnapshot):
                raise ProposalError(
                    "INVALID_ARGUMENT", "A validated canonical Snapshot is required"
                )
            try:
                snapshot = CanonicalSnapshot(snapshot.canonical_text, snapshot.snapshot_hash)
            except (ValueError, TypeError) as error:
                raise ProposalError("INVALID_ARGUMENT", "Invalid proposal Snapshot") from error
            payload = snapshot.data
            if payload["requester_id"] != context.authenticated_user_id:
                raise ProposalError("AUTHORIZATION_DENIED", "Snapshot requester does not match")
            category = CATEGORIES[payload["targets"][0]["target_type"]]
            if context.role not in REQUEST_ROLES[category]:
                raise ProposalError("AUTHORIZATION_DENIED", "Update request permission is required")
            replacement = payload["supersedes_update_request_id"]
            if replacement is not None:
                previous = lock_replaced_request(connection, replacement)
                if previous is None:
                    raise ProposalError("TARGET_NOT_FOUND", "Replacement request was not found")
                if previous["requester_id"] != context.authenticated_user_id:
                    raise ProposalError("AUTHORIZATION_DENIED", "Only the requester may replace")
                lock_request_approval(connection, replacement)
                # Another retry may have committed while we waited for the old
                # request lock. Return that result before checking its old state.
                row = connection.execute(LOOKUP, (context.authenticated_user_id, key)).fetchone()
                if row:
                    return _saved(row, prepare_input_hash, agent_input_hash, replayed=True)
                old_row = connection.execute(
                    LOOKUP, (context.authenticated_user_id, previous["prepare_retry_key"])
                ).fetchone()
                old = _saved(old_row, None, None, replayed=False)
                if (old.status, old.approval_status) not in {
                    ("WAITING_APPROVAL", "PENDING"),
                    ("APPROVED", "APPROVED"),
                }:
                    raise ProposalError("INVALID_UPDATE_STATE", "Replacement request is terminal")
            request_id, idempotency_key = uuid4(), uuid4()
            inserted = insert_pending_request(
                connection,
                request_id=request_id,
                requester_id=context.authenticated_user_id,
                operation_type=_operation(payload["targets"]),
                idempotency_key=idempotency_key,
                retry_key=key,
                prepare_input_hash=prepare_input_hash,
                agent_input_hash=agent_input_hash,
                snapshot=snapshot,
            )
            if inserted:
                for target in payload["targets"]:
                    insert_proposal_target(
                        connection, target_row_id=uuid4(), request_id=request_id, target=target
                    )
                approval_id = uuid4()
                insert_pending_approval(
                    connection,
                    approval_id=approval_id,
                    request_id=request_id,
                    snapshot_hash=snapshot.snapshot_hash,
                )
                if replacement is not None:
                    invalidate_replaced_request(connection, replacement)
                    invalidate_replaced_approval(connection, replacement)
                    proposal_replaced(connection, context, old, request_id)
                prepare_saved(connection, context, request_id, approval_id, len(payload["targets"]))
            # ON CONFLICT may wait for another commit. READ COMMITTED gives the
            # next statement a fresh snapshot containing the committed winner.
            row = connection.execute(LOOKUP, (context.authenticated_user_id, key)).fetchone()
            if row is None:
                raise ProposalError("INTERNAL_ERROR", "Saved proposal could not be verified")
            return _saved(row, prepare_input_hash, agent_input_hash, replayed=inserted is None)
