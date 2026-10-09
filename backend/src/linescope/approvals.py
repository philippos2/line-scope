"""Human approval transactions with explicit category/operation admission.

HTTP admission supports equipment state and maintenance plan UPDATE. CREATE,
records, assignment and Graph validation follow.
"""

from uuid import uuid4

from psycopg.types.json import Jsonb

from .approval_policy import validate_approve, validate_reject
from .audit import failed_attempt
from .canonical import normalize_timestamp, normalize_uuid
from .execution import ExecutionContext
from .logging import EventLogger, request_context
from .proposals import LOOKUP, ProposalError, ProposalStore, _saved


class _HumanApproval:
    def __init__(self, database, event_logger=None):
        self.store = ProposalStore(database)
        self.events = event_logger or EventLogger()

    def _approve(self, context, approval_id, snapshot_hash):
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
            self._require_scope(category, saved)
            targets = saved.snapshot.data["targets"]
            conflict = self._targets_changed(connection, targets)
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
            error = ProposalError("VERSION_CONFLICT", "The prepared target has changed")
            error.update_request_id = request_id
            raise error
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

    def _reject(self, context, approval_id):
        """Reject a pending proposal; never cancel an approval."""
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        try:
            approval_id = normalize_uuid(approval_id)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "A valid Approval ID is required") from error
        with self.store._transaction() as connection:
            saved = self._locked_proposal(connection, approval_id)
            self._require_scope(validate_reject(context, saved), saved)
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
            "approved_at": None,
            "expires_at": None,
        }

    def approve(self, context, approval_id, snapshot_hash):
        return self._observed(context, approval_id, "APPROVE", snapshot_hash)

    def reject(self, context, approval_id):
        return self._observed(context, approval_id, "REJECT")

    def _observed(self, context, approval_id, action, snapshot_hash=None):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        with request_context(
            context.request_id, actor_id=context.authenticated_user_id, role=context.role
        ):
            try:
                result = (
                    self._approve(context, approval_id, snapshot_hash)
                    if action == "APPROVE"
                    else self._reject(context, approval_id)
                )
            except ProposalError as error:
                # VERSION_CONFLICT already committed an INVALIDATE audit in _approve.
                request_id = getattr(error, "update_request_id", None)
                if error.code != "VERSION_CONFLICT":
                    request_id = self._failure_audit(context, approval_id, action, error.code)
                self.events.emit(
                    "approval.completed",
                    component="proposal",
                    outcome="unknown"
                    if error.code == "DEPENDENCY_UNAVAILABLE"
                    else "failure"
                    if error.code == "INTERNAL_ERROR"
                    else "rejected",
                    result_code=error.code,
                    level="ERROR"
                    if error.code == "INTERNAL_ERROR"
                    else "WARNING"
                    if error.code in {"DEPENDENCY_UNAVAILABLE", "RESOURCE_BUSY"}
                    else "INFO",
                    approval_id=approval_id,
                    update_request_id=request_id,
                    before_status="WAITING_APPROVAL" if error.code == "VERSION_CONFLICT" else None,
                    after_status="INVALIDATED" if error.code == "VERSION_CONFLICT" else None,
                    error=error if error.code == "INTERNAL_ERROR" else None,
                )
                raise
            self.events.emit(
                "approval.completed",
                component="proposal",
                outcome="success",
                result_code="OK",
                update_request_id=result["update_request_id"],
                approval_id=result["approval_id"],
                before_status="WAITING_APPROVAL",
                after_status=result["status"],
            )
            return result

    def _failure_audit(self, context, approval_id, action, code):
        return failed_attempt(
            self.store, self.events, context, action, code, approval_id=approval_id
        )


class EquipmentApproval(_HumanApproval):
    @staticmethod
    def _require_scope(category, saved):
        if category != "EQUIPMENT_STATE":
            raise ProposalError(
                "INVALID_ARGUMENT", "This transaction supports equipment state only"
            )

    @staticmethod
    def _targets_changed(connection, targets):
        conflict = False
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
        return conflict


class MaintenancePlanUpdateApproval(_HumanApproval):
    @staticmethod
    def _require_scope(category, saved):
        if category != "MAINTENANCE" or any(
            t["target_type"] != "MaintenancePlan" or t["operation_type"] != "UPDATE"
            for t in saved.snapshot.data["targets"]
        ):
            raise ProposalError(
                "INVALID_ARGUMENT", "This transaction supports maintenance plan UPDATE only"
            )

    @staticmethod
    def _targets_changed(connection, targets):
        conflict = False
        for target in targets:
            current = connection.execute(
                "SELECT maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status,version "
                "FROM maintenance_plan WHERE maintenance_plan_id=%s FOR UPDATE",
                (target["target_id"],),
            ).fetchone()
            if current is None:
                conflict = True
                continue
            current = {
                **current,
                "maintenance_plan_id": str(current["maintenance_plan_id"]),
                "equipment_id": str(current["equipment_id"]),
                "planned_start": normalize_timestamp(current["planned_start"]),
                "planned_end": normalize_timestamp(current["planned_end"]),
            }
            if current != target["before"]:
                conflict = True
        return conflict


class HumanApproval(_HumanApproval):
    """Dispatch only supported saved Targets, inside the shared locked transaction."""

    @staticmethod
    def _require_scope(category, saved):
        if category == "EQUIPMENT_STATE":
            EquipmentApproval._require_scope(category, saved)
        elif category == "MAINTENANCE":
            MaintenancePlanUpdateApproval._require_scope(category, saved)
        else:
            raise ProposalError("INVALID_ARGUMENT", "This approval category is not supported yet")

    @staticmethod
    def _targets_changed(connection, targets):
        # Canonical validation enforces one category; _require_scope has checked
        # every Target before any business row is read or transition is written.
        handler = (
            EquipmentApproval
            if targets[0]["target_type"] == "EquipmentState"
            else MaintenancePlanUpdateApproval
        )
        return handler._targets_changed(connection, targets)
