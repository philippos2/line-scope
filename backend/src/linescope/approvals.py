"""Internal human Approval transaction for equipment-state proposals only.

No Agent Tool or HTTP publication. Other categories need their own current-row
and CREATE/assignment/Graph validation before admission can be enabled.
"""

from uuid import uuid4

from psycopg.types.json import Jsonb

from .approval_policy import validate_approve, validate_reject
from .canonical import normalize_uuid
from .execution import ExecutionContext
from .proposals import LOOKUP, ProposalError, ProposalStore, _saved


class EquipmentApproval:
    def __init__(self, database):
        self.store = ProposalStore(database)

    def approve(self, context, approval_id, snapshot_hash):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        try:
            approval_id = normalize_uuid(approval_id)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "A valid Approval ID is required") from error
        conflict = False
        with self.store._transaction() as connection:
            saved = self._locked_proposal(connection, approval_id)
            request_id = saved.update_request_id
            category = validate_approve(context, saved, snapshot_hash)
            if category != "EQUIPMENT_STATE":
                raise ProposalError(
                    "INVALID_ARGUMENT", "This transaction supports equipment state only"
                )
            targets = saved.snapshot.data["targets"]
            for target in targets:
                current = connection.execute(
                    "SELECT equipment_id,state_code,version FROM equipment_current_state "
                    "WHERE equipment_id=%s FOR UPDATE",
                    (target["target_id"],),
                ).fetchone()
                if (
                    current is None
                    or {
                        "equipment_id": str(current["equipment_id"]),
                        "state_code": current["state_code"],
                        "version": current["version"],
                    }
                    != target["before"]
                ):
                    conflict = True
            if conflict:
                status, action, code = "INVALIDATED", "INVALIDATE", "VERSION_CONFLICT"
                connection.execute(
                    "UPDATE approval SET status='INVALIDATED',updated_at=clock_timestamp() WHERE approval_id=%s",
                    (approval_id,),
                )
                result = None
            else:
                status, action, code = "APPROVED", "APPROVE", "OK"
                times = connection.execute(
                    "WITH now AS (SELECT clock_timestamp() AS approved_at) "
                    "UPDATE approval SET status='APPROVED',approver_id=%s,approved_at=now.approved_at,"
                    "expires_at=now.approved_at+INTERVAL '30 minutes',updated_at=now.approved_at "
                    "FROM now WHERE approval_id=%s RETURNING approval.approved_at,approval.expires_at",
                    (context.authenticated_user_id, approval_id),
                ).fetchone()
                result = {
                    "update_request_id": request_id,
                    "approval_id": saved.approval_id,
                    "status": status,
                    "approval_status": status,
                    **times,
                }
            connection.execute(
                "UPDATE update_request SET status=%s,updated_at=clock_timestamp() WHERE update_request_id=%s",
                (status, request_id),
            )
            connection.execute(
                "INSERT INTO update_audit_event(audit_event_id,request_id,update_request_id,approval_id,"
                "actor_id,action,before_status,after_status,result_code,details,occurred_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,'WAITING_APPROVAL',%s,%s,%s,clock_timestamp())",
                (
                    uuid4(),
                    context.request_id,
                    request_id,
                    approval_id,
                    context.authenticated_user_id,
                    action,
                    status,
                    code,
                    Jsonb({"target_count": len(targets)}),
                ),
            )
        # Invalidation must commit before reporting the conflict to the caller.
        if conflict:
            raise ProposalError("VERSION_CONFLICT", "The prepared equipment state has changed")
        return result

    @staticmethod
    def _locked_proposal(connection, approval_id):
        parent = connection.execute(
            "SELECT update_request_id FROM approval WHERE approval_id=%s", (approval_id,)
        ).fetchone()
        if parent is None:
            raise ProposalError("TARGET_NOT_FOUND", "Approval was not found")
        request_id = parent["update_request_id"]
        connection.execute(
            "SELECT update_request_id FROM update_request WHERE update_request_id=%s FOR UPDATE",
            (request_id,),
        ).fetchone()
        locked = connection.execute(
            "SELECT approval_id FROM approval WHERE approval_id=%s AND update_request_id=%s FOR UPDATE",
            (approval_id, request_id),
        ).fetchone()
        if locked is None:
            raise ProposalError("TARGET_NOT_FOUND", "Approval was not found")
        query = LOOKUP.replace(
            "WHERE r.requester_id=%s AND r.prepare_retry_key=%s", "WHERE r.update_request_id=%s"
        )
        row = connection.execute(query, (request_id,)).fetchone()
        return _saved(row, None, None, replayed=False)

    def reject(self, context, approval_id):
        """Reject a pending equipment proposal; never cancel an approval."""
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        try:
            approval_id = normalize_uuid(approval_id)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "A valid Approval ID is required") from error
        with self.store._transaction() as connection:
            saved = self._locked_proposal(connection, approval_id)
            if validate_reject(context, saved) != "EQUIPMENT_STATE":
                raise ProposalError(
                    "INVALID_ARGUMENT", "This transaction supports equipment state only"
                )
            connection.execute(
                "UPDATE approval SET status='REJECTED',approver_id=%s,updated_at=clock_timestamp() WHERE approval_id=%s",
                (context.authenticated_user_id, approval_id),
            )
            connection.execute(
                "UPDATE update_request SET status='REJECTED',updated_at=clock_timestamp() WHERE update_request_id=%s",
                (saved.update_request_id,),
            )
            connection.execute(
                "INSERT INTO update_audit_event(audit_event_id,request_id,update_request_id,approval_id,"
                "actor_id,action,before_status,after_status,result_code,details,occurred_at) "
                "VALUES(%s,%s,%s,%s,%s,'REJECT','WAITING_APPROVAL','REJECTED','OK',%s,clock_timestamp())",
                (
                    uuid4(),
                    context.request_id,
                    saved.update_request_id,
                    approval_id,
                    context.authenticated_user_id,
                    Jsonb({"target_count": len(saved.snapshot.data["targets"])}),
                ),
            )
        return {
            "update_request_id": saved.update_request_id,
            "approval_id": saved.approval_id,
            "status": "REJECTED",
            "approval_status": "REJECTED",
        }
