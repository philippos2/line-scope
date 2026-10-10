"""Human approval transactions with explicit category/operation admission.

HTTP admission supports equipment state, maintenance, and schedule-only production requests.
Assignment-aware production and Graph validation follow.
"""

from uuid import uuid4

from psycopg.types.json import Jsonb

from .approval_policy import validate_approve, validate_reject
from .assignments import normalize_operation_assignments
from .audit import failed_attempt
from .canonical import normalize_timestamp, normalize_uuid
from .core_approval_updates import (
    approve_proposal_state,
    invalidate_proposal_state,
    reject_proposal_state,
)
from .execution import ExecutionContext
from .logging import EventLogger, request_context
from .proposals import LOOKUP, ProposalError, ProposalStore, _saved
from .relations import KEY_FIELDS, normalize_relation_set


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
            conflict = self._conflict_code(connection, targets)
            if conflict:
                status, action, code = "INVALIDATED", "INVALIDATE", conflict
                invalidate_proposal_state(connection, approval_id, request_id)
                result = None
            else:
                status, action, code = "APPROVED", "APPROVE", "OK"
                times = approve_proposal_state(
                    connection, approval_id, request_id, context.authenticated_user_id
                )
                result = {
                    "update_request_id": request_id,
                    "approval_id": saved.approval_id,
                    "status": status,
                    "approval_status": status,
                    **times,
                }
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
            error = ProposalError(conflict, "The prepared target is no longer valid")
            error.update_request_id = request_id
            error.transition_committed = True
            raise error
        return result

    @classmethod
    def _conflict_code(cls, connection, targets):
        return "VERSION_CONFLICT" if cls._targets_changed(connection, targets) else None

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
            reject_proposal_state(
                connection, approval_id, saved.update_request_id, context.authenticated_user_id
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
                # A committed invalidation already has an atomic INVALIDATE audit.
                request_id = getattr(error, "update_request_id", None)
                invalidated = getattr(error, "transition_committed", False)
                if not invalidated:
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
                    before_status="WAITING_APPROVAL" if invalidated else None,
                    after_status="INVALIDATED" if invalidated else None,
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


class MaintenancePlanCreateApproval(_HumanApproval):
    """Approve saved plan CREATEs without inserting any business rows."""

    @staticmethod
    def _require_scope(category, saved):
        if category != "MAINTENANCE" or any(
            t["target_type"] != "MaintenancePlan" or t["operation_type"] != "CREATE"
            for t in saved.snapshot.data["targets"]
        ):
            raise ProposalError(
                "INVALID_ARGUMENT", "This transaction supports maintenance plan CREATE only"
            )

    @staticmethod
    def _conflict_code(connection, targets):
        # Nonexistent CREATE rows cannot be locked. This is the approval-time
        # observation only; Execute must recheck and rely on DB UNIQUE at INSERT.
        row = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM maintenance_plan "
            "WHERE maintenance_plan_id=ANY(%s::uuid[]) OR plan_code=ANY(%s::text[])) AS conflict",
            (
                [t["target_id"] for t in targets],
                [t["after"]["plan_code"] for t in targets],
            ),
        ).fetchone()
        return "CREATE_CONFLICT" if row["conflict"] else None


class MaintenanceRecordCreateApproval(_HumanApproval):
    """Record CREATE approval; reference revalidation belongs to Execute."""

    @staticmethod
    def _require_scope(category, saved):
        if category != "MAINTENANCE" or any(
            t["target_type"] != "MaintenanceRecord" or t["operation_type"] != "CREATE"
            for t in saved.snapshot.data["targets"]
        ):
            raise ProposalError(
                "INVALID_ARGUMENT", "This transaction supports maintenance record CREATE only"
            )

    @staticmethod
    def _conflict_code(connection, targets):
        row = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM maintenance_record "
            "WHERE maintenance_record_id=ANY(%s::uuid[]) OR record_code=ANY(%s::text[])) AS conflict",
            (
                [t["target_id"] for t in targets],
                [t["after"]["record_code"] for t in targets],
            ),
        ).fetchone()
        return "CREATE_CONFLICT" if row["conflict"] else None


class ProductionScheduleApproval(_HumanApproval):
    """Internal schedule-only approval; assignment-aware requests remain deferred."""

    @staticmethod
    def _require_scope(category, saved):
        if category != "PRODUCTION_OPERATION" or any(
            t["target_type"] != "ProductionOperation"
            or t["operation_type"] != "UPDATE"
            or "equipment_assignments" in t["before"]
            or "equipment_assignments" in t["after"]
            for t in saved.snapshot.data["targets"]
        ):
            raise ProposalError("INVALID_ARGUMENT", "Production schedule UPDATE targets required")

    @staticmethod
    def _targets_changed(connection, targets):
        conflict = False
        for target in targets:
            row = connection.execute(
                "SELECT production_operation_id,operation_code,process_id,planned_status,"
                "planned_start,planned_end,active,version FROM production_operation "
                "WHERE production_operation_id=%s FOR UPDATE",
                (target["target_id"],),
            ).fetchone()
            if row is None:
                conflict = True
                continue
            current = {
                **row,
                "production_operation_id": str(row["production_operation_id"]),
                "process_id": str(row["process_id"]),
                "planned_start": normalize_timestamp(row["planned_start"]),
                "planned_end": normalize_timestamp(row["planned_end"]),
            }
            if current != target["before"]:
                conflict = True
        return conflict


class ProductionAssignmentApproval(_HumanApproval):
    """Assignment-aware human approval; Graph/endpoint checks belong to Execute."""

    @staticmethod
    def _require_scope(category, saved):
        targets = saved.snapshot.data["targets"]
        allowed = {
            ("ProductionOperation", "UPDATE"),
            ("ProductionOperationEquipmentAssignment", "CREATE"),
            ("ProductionOperationEquipmentAssignment", "UPDATE"),
            ("ProductionOperationEquipmentAssignment", "DISABLE"),
        }
        if (
            category != "PRODUCTION_OPERATION"
            or any((t["target_type"], t["operation_type"]) not in allowed for t in targets)
            or not any(
                t["target_type"] == "ProductionOperation" and "equipment_assignments" in t["before"]
                for t in targets
            )
        ):
            raise ProposalError("INVALID_ARGUMENT", "Assignment-aware production targets required")

    @staticmethod
    def _conflict_code(connection, targets):
        parents = [t for t in targets if t["target_type"] == "ProductionOperation"]
        # Lock all parents before children, including schedule-only parents in
        # this request. Compare their complete business rows without the set.
        plain = [
            {**t, "before": {k: v for k, v in t["before"].items() if k != "equipment_assignments"}}
            for t in parents
        ]
        if ProductionScheduleApproval._targets_changed(connection, plain):
            return "VERSION_CONFLICT"
        children = [
            t for t in targets if t["target_type"] == "ProductionOperationEquipmentAssignment"
        ]
        changed_ids = [t["target_id"] for t in children if t["operation_type"] != "CREATE"]
        rows = connection.execute(
            "SELECT to_jsonb(a)-'created_at'-'updated_at' AS state "
            "FROM production_operation_equipment_assignment a "
            "WHERE production_operation_id=ANY(%s::uuid[]) OR assignment_id=ANY(%s::uuid[]) "
            "ORDER BY assignment_id FOR UPDATE",
            ([t["target_id"] for t in parents], changed_ids),
        ).fetchall()
        try:
            current = {
                row["state"]["assignment_id"]: normalize_operation_assignments(
                    row["state"]["production_operation_id"], [row["state"]]
                )[0]
                for row in rows
            }
        except ValueError:
            return "VERSION_CONFLICT"
        for parent in parents:
            if "equipment_assignments" not in parent["before"]:
                continue
            active = sorted(
                [
                    r
                    for r in current.values()
                    if r["production_operation_id"] == parent["target_id"] and r["active"]
                ],
                key=lambda r: r["assignment_id"],
            )
            if active != parent["before"]["equipment_assignments"]:
                return "VERSION_CONFLICT"
        if any(
            current.get(t["target_id"]) != t["before"]
            for t in children
            if t["operation_type"] != "CREATE"
        ):
            return "VERSION_CONFLICT"
        creates = [t for t in children if t["operation_type"] == "CREATE"]
        if not creates:
            return None
        # CREATE rows cannot be locked before they exist. This observation is
        # rechecked by Execute under Graph coordination and DB UNIQUE.
        conflict = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM production_operation_equipment_assignment "
            "WHERE assignment_id=ANY(%s::uuid[])) OR EXISTS(SELECT 1 "
            "FROM production_operation_equipment_assignment a JOIN jsonb_to_recordset(%s) "
            "AS k(production_operation_id uuid,equipment_id uuid,effective_from timestamptz) "
            "ON a.production_operation_id=k.production_operation_id AND a.equipment_id=k.equipment_id "
            "AND a.effective_from=k.effective_from) AS conflict",
            ([t["target_id"] for t in creates], Jsonb([t["business_key"] for t in creates])),
        ).fetchone()["conflict"]
        return "CREATE_CONFLICT" if conflict else None


class DependencyApproval(_HumanApproval):
    """Internal dependency approval; Execute revalidates under the Graph lock."""

    @staticmethod
    def _require_scope(category, saved):
        if category != "DEPENDENCY" or any(
            t["target_type"] != "DependencyRelation"
            or t["operation_type"] not in {"CREATE", "UPDATE", "DISABLE"}
            for t in saved.snapshot.data["targets"]
        ):
            raise ProposalError("INVALID_ARGUMENT", "Dependency relation targets required")

    @staticmethod
    def _conflict_code(connection, targets):
        changed = []
        for target in targets:
            if target["operation_type"] == "CREATE":
                continue
            changed.append(target["target_id"])
            row = connection.execute(
                "SELECT to_jsonb(r)-'created_at'-'updated_at' AS state "
                "FROM dependency_relation r WHERE dependency_relation_id=%s FOR UPDATE",
                (target["target_id"],),
            ).fetchone()
            try:
                current = normalize_relation_set([row["state"]])[0] if row else None
            except ValueError:
                current = None
            if current != target["before"]:
                return "VERSION_CONFLICT"
        # Compare final keys against unchanged rows. Another Target may move
        # its old key in the same transaction; do not reject that key transfer.
        keys = [{field: t["after"][field] for field in KEY_FIELDS} for t in targets]
        row = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM dependency_relation "
            "WHERE dependency_relation_id=ANY(%s::uuid[])) OR EXISTS("
            "SELECT 1 FROM dependency_relation r JOIN jsonb_to_recordset(%s) AS k("
            "source_entity_type text,source_entity_id uuid,target_entity_type text,"
            "target_entity_id uuid,relation_type text,effective_from timestamptz) ON "
            "r.source_entity_type=k.source_entity_type AND r.source_entity_id=k.source_entity_id "
            "AND r.target_entity_type=k.target_entity_type AND r.target_entity_id=k.target_entity_id "
            "AND r.relation_type=k.relation_type AND r.effective_from=k.effective_from "
            "WHERE NOT r.dependency_relation_id=ANY(%s::uuid[])) AS conflict",
            (
                [t["target_id"] for t in targets if t["operation_type"] == "CREATE"],
                Jsonb(keys),
                changed,
            ),
        ).fetchone()
        return "CREATE_CONFLICT" if row["conflict"] else None


class MaintenanceApproval(_HumanApproval):
    """Approve the whole maintenance category, without changing business rows."""

    HANDLERS = {
        ("MaintenancePlan", "UPDATE"): MaintenancePlanUpdateApproval,
        ("MaintenancePlan", "CREATE"): MaintenancePlanCreateApproval,
        ("MaintenanceRecord", "CREATE"): MaintenanceRecordCreateApproval,
    }

    @classmethod
    def _require_scope(cls, category, saved):
        targets = saved.snapshot.data["targets"]
        if (
            category != "MAINTENANCE"
            or not targets
            or any((t["target_type"], t["operation_type"]) not in cls.HANDLERS for t in targets)
        ):
            raise ProposalError("INVALID_ARGUMENT", "Maintenance targets required")

    @classmethod
    def _conflict_code(cls, connection, targets):
        # UPDATE rows are locked in canonical ID order before CREATE observations.
        # One conflict invalidates the single request/approval, never a subset.
        for key, handler in cls.HANDLERS.items():
            group = [t for t in targets if (t["target_type"], t["operation_type"]) == key]
            if group:
                conflict = handler._conflict_code(connection, group)
                if conflict:
                    return conflict
        return None


class HumanApproval(_HumanApproval):
    """Dispatch only supported saved Targets, inside the shared locked transaction."""

    @classmethod
    def _require_scope(cls, category, saved):
        cls._handler(saved.snapshot.data["targets"])._require_scope(category, saved)

    @staticmethod
    def _handler(targets):
        if targets and all(t["target_type"] == "DependencyRelation" for t in targets):
            return DependencyApproval
        if any("equipment_assignments" in (t["after"] or {}) for t in targets):
            return ProductionAssignmentApproval
        handlers = {
            ("EquipmentState", "UPDATE"): EquipmentApproval,
            ("ProductionOperation", "UPDATE"): ProductionScheduleApproval,
            ("MaintenancePlan", "UPDATE"): MaintenancePlanUpdateApproval,
            ("MaintenancePlan", "CREATE"): MaintenancePlanCreateApproval,
            ("MaintenanceRecord", "CREATE"): MaintenanceRecordCreateApproval,
        }
        keys = {(t["target_type"], t["operation_type"]) for t in targets}
        if len(keys) > 1 and keys <= MaintenanceApproval.HANDLERS.keys():
            return MaintenanceApproval
        key = next(iter(keys)) if len(keys) == 1 else None
        if key not in handlers:
            raise ProposalError("INVALID_ARGUMENT", "This approval category is not supported yet")
        # The selected scope validates every Target, including operation type.
        return handlers[key]

    @classmethod
    def _conflict_code(cls, connection, targets):
        return cls._handler(targets)._conflict_code(connection, targets)
