"""Shared update execution with explicit equipment and plan-UPDATE admission."""

from uuid import uuid4

from psycopg.errors import ForeignKeyViolation, UniqueViolation
from psycopg.types.json import Jsonb

from .approvals import HumanApproval, MaintenancePlanCreateApproval, MaintenancePlanUpdateApproval
from .audit import failed_attempt
from .canonical import normalize_timestamp, normalize_uuid
from .execute_policy import ApprovalFacts, validate_new_execute
from .execution import ExecutionContext
from .logging import EventLogger, request_context
from .proposals import LOOKUP, ProposalError, ProposalStore, _saved
from .reads import json_value
from .snapshot import CATEGORIES

RETIRE_CODES = frozenset(
    {
        "VERSION_CONFLICT",
        "CREATE_CONFLICT",
        "BUSINESS_RULE_VIOLATION",
        "APPROVAL_EXPIRED",
        "APPROVAL_INVALIDATED",
    }
)


class _UpdateExecute:
    def __init__(self, database, settings, event_logger=None):
        self.store = ProposalStore(database)
        self.events = event_logger or EventLogger()
        self.roles = {user["user_id"]: user["role"] for user in settings.users.values()}

    def _load(self, c, request_id):
        row = c.execute(
            "SELECT * FROM update_request WHERE update_request_id=%s FOR UPDATE", (request_id,)
        ).fetchone()
        if row is None:
            raise ProposalError("TARGET_NOT_FOUND", "Update request was not found")
        c.execute(
            "SELECT approval_id FROM approval WHERE update_request_id=%s FOR UPDATE", (request_id,)
        ).fetchone()
        row = c.execute(
            LOOKUP.replace(
                "WHERE r.requester_id=%s AND r.prepare_retry_key=%s", "WHERE r.update_request_id=%s"
            ),
            (request_id,),
        ).fetchone()
        saved = _saved(row, None, None, replayed=False)
        approval = c.execute(
            "SELECT * FROM approval WHERE update_request_id=%s", (request_id,)
        ).fetchone()
        return row, saved, approval

    def _validate(self, c, context, saved, approval):
        facts = ApprovalFacts(
            approval["approver_id"],
            self.roles.get(approval["approver_id"]),
            approval["snapshot_hash"],
            approval["approved_at"],
            approval["expires_at"],
            approval["consumed_at"],
        )
        now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        validate_new_execute(context, saved, facts, now=now)
        self._require_scope(saved)
        return now

    def _run(self, context, request_id, attempt):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        try:
            request_id = normalize_uuid(request_id)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Valid update request ID required") from error
        try:
            return self._execute(context, request_id, attempt)
        except ProposalError as error:
            if error.code in RETIRE_CODES:
                replay = self._retire(context, request_id)
                if replay is not None:
                    attempt["replayed"] = True
                    return replay
            raise

    def _execute(self, context, request_id, attempt):
        with self.store._transaction() as c:
            row, saved, approval = self._load(c, request_id)
            attempt["approval_id"] = saved.approval_id
            if row["requester_id"] != context.authenticated_user_id:
                raise ProposalError("AUTHORIZATION_DENIED", "Only requester may execute")
            self._require_scope(saved)
            if saved.status == "COMPLETED":
                attempt["replayed"] = True
                return row["execution_result"]
            self._validate(c, context, saved, approval)
            targets = self._targets(c, saved)
            executed_at = self._validate(c, context, saved, approval)
            self._apply(c, request_id, targets, executed_at)
            history_id = uuid4()
            result = json_value(
                {
                    "targets": targets,
                    "history_id": history_id,
                    "approval_id": saved.approval_id,
                    "executed_at": executed_at,
                }
            )
            snapshots = [
                {
                    "targets": [
                        {
                            "target_type": t["target_type"],
                            "target_id": t["target_id"],
                            "snapshot": t[side],
                        }
                        for t in targets
                    ]
                }
                for side in ("before", "after")
            ]
            c.execute(
                "INSERT INTO business_update_history(history_id,update_request_id,approval_id,requester_id,approver_id,category,before_snapshot,after_snapshot,result,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'OK',%s)",
                (
                    history_id,
                    request_id,
                    saved.approval_id,
                    row["requester_id"],
                    approval["approver_id"],
                    CATEGORIES[targets[0]["target_type"]],
                    Jsonb(snapshots[0]),
                    Jsonb(snapshots[1]),
                    executed_at,
                ),
            )
            self._validate(c, context, saved, approval)
            consumed = c.execute(
                "WITH t AS MATERIALIZED (SELECT clock_timestamp() AS at) "
                "UPDATE approval SET status='CONSUMED',consumed_at=t.at,updated_at=t.at "
                "FROM t WHERE approval_id=%s AND t.at<expires_at RETURNING consumed_at",
                (saved.approval_id,),
            ).fetchone()
            if consumed is None:
                raise ProposalError(
                    "APPROVAL_EXPIRED", "Approval deadline reached before consumption"
                )
            consumed_at = consumed["consumed_at"]
            c.execute(
                "UPDATE update_request SET status='COMPLETED',execution_result=%s,updated_at=%s WHERE update_request_id=%s",
                (Jsonb(result), consumed_at, request_id),
            )
            self._audit(c, context, saved, "EXECUTE", "COMPLETED", "OK")
        return result

    @staticmethod
    def _audit(c, context, saved, action, status, code):
        c.execute(
            "INSERT INTO update_audit_event(audit_event_id,request_id,update_request_id,approval_id,actor_id,action,before_status,after_status,result_code,details,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,'APPROVED',%s,%s,%s,clock_timestamp())",
            (
                uuid4(),
                context.request_id,
                saved.update_request_id,
                saved.approval_id,
                context.authenticated_user_id,
                action,
                status,
                code,
                Jsonb({}),
            ),
        )

    def _retire(self, context, request_id):
        with self.store._transaction() as c:
            row, saved, approval = self._load(c, request_id)
            if row["requester_id"] != context.authenticated_user_id:
                return None
            self._require_scope(saved)
            if saved.status == "COMPLETED":
                return row["execution_result"]
            if (saved.status, saved.approval_status) != ("APPROVED", "APPROVED"):
                return None
            try:
                self._validate(c, context, saved, approval)
                self._targets(c, saved)
            except ProposalError as error:
                if error.code not in RETIRE_CODES:
                    raise
                status = "EXPIRED" if error.code == "APPROVAL_EXPIRED" else "INVALIDATED"
                c.execute(
                    "UPDATE approval SET status=%s,updated_at=clock_timestamp() WHERE approval_id=%s",
                    (status, saved.approval_id),
                )
                c.execute(
                    "UPDATE update_request SET status=%s,updated_at=clock_timestamp() WHERE update_request_id=%s",
                    (status, request_id),
                )
                self._audit(
                    c,
                    context,
                    saved,
                    "EXPIRE" if status == "EXPIRED" else "INVALIDATE",
                    status,
                    error.code,
                )
        return None

    def execute(self, context, request_id):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        attempt = {"replayed": False, "approval_id": None}
        with request_context(
            context.request_id, actor_id=context.authenticated_user_id, role=context.role
        ):
            try:
                result = self._run(context, request_id, attempt)
            except ProposalError as error:
                failed_attempt(
                    self.store, self.events, context, "EXECUTE", error.code, request_id=request_id
                )
                unknown = error.code == "DEPENDENCY_UNAVAILABLE"
                self.events.emit(
                    "execution.outcome_unknown" if unknown else "execute.completed",
                    component="proposal",
                    outcome="unknown"
                    if unknown
                    else "failure"
                    if error.code == "INTERNAL_ERROR"
                    else "rejected",
                    result_code=error.code,
                    level="ERROR"
                    if unknown or error.code == "INTERNAL_ERROR"
                    else "WARNING"
                    if error.code == "RESOURCE_BUSY"
                    else "INFO",
                    update_request_id=request_id,
                    approval_id=attempt["approval_id"],
                    error=error if error.code == "INTERNAL_ERROR" else None,
                )
                raise
            self.events.emit(
                "execute.completed",
                component="proposal",
                outcome="success",
                result_code="OK",
                update_request_id=request_id,
                approval_id=result["approval_id"],
                replayed=attempt["replayed"],
                before_status="COMPLETED" if attempt["replayed"] else "APPROVED",
                after_status="COMPLETED",
            )
            return result


class EquipmentExecute(_UpdateExecute):
    category = "EQUIPMENT_STATE"

    @staticmethod
    def _require_scope(saved):
        if CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]] != "EQUIPMENT_STATE":
            raise ProposalError("INVALID_ARGUMENT", "Equipment state only")

    @staticmethod
    def _targets(c, saved):
        targets = saved.snapshot.data["targets"]
        conflict = False
        for target in targets:
            current = c.execute(
                "SELECT equipment_id,state_code,version FROM equipment_current_state WHERE equipment_id=%s FOR UPDATE",
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
            raise ProposalError("VERSION_CONFLICT", "Equipment state has changed")
        return targets

    @staticmethod
    def _apply(c, request_id, targets, executed_at):
        for target in targets:
            result = c.execute(
                "UPDATE equipment_current_state SET state_code=%s,version=version+1,updated_at=%s WHERE equipment_id=%s AND version=%s",
                (
                    target["after"]["state_code"],
                    executed_at,
                    target["target_id"],
                    target["expected_version"],
                ),
            )
            if result.rowcount != 1:
                raise ProposalError("VERSION_CONFLICT", "Equipment version has changed")
            c.execute(
                "INSERT INTO equipment_state_history(history_id,equipment_id,update_request_id,state_code,effective_at,recorded_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    target["target_id"],
                    request_id,
                    target["after"]["state_code"],
                    executed_at,
                    executed_at,
                ),
            )

    def observe_current(self, result):
        """One statement observes all current targets after the execution commit."""
        targets = result["targets"]
        ids = [target["target_id"] for target in targets]
        with self.store._transaction(read_only=True) as c:
            row = c.execute(
                "SELECT statement_timestamp() AS observed_at, "
                "(SELECT jsonb_agg(jsonb_build_object('equipment_id',equipment_id,"
                "'state_code',state_code,'version',version,'updated_at',updated_at) ORDER BY equipment_id) "
                "FROM equipment_current_state WHERE equipment_id=ANY(%s::uuid[])) AS states",
                (ids,),
            ).fetchone()
        states = row["states"] or []
        if len(states) != len(targets):
            raise ProposalError("TARGET_NOT_FOUND", "A current target is unavailable")
        confirmed = {t["target_id"]: t["after"]["version"] for t in targets}
        return {
            "current_snapshot": {
                "targets": [
                    {"target_type": "EquipmentState", "target_id": s["equipment_id"], "snapshot": s}
                    for s in states
                ]
            },
            "current_versions": [
                {
                    "target_type": "EquipmentState",
                    "target_id": s["equipment_id"],
                    "version": s["version"],
                    "confirmed_version": confirmed[s["equipment_id"]],
                    "version_delta": s["version"] - confirmed[s["equipment_id"]],
                }
                for s in states
            ],
            "observed_at": row["observed_at"],
        }


class MaintenancePlanUpdateExecute(_UpdateExecute):
    category = "MAINTENANCE"

    @staticmethod
    def _require_scope(saved):
        category = CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]]
        MaintenancePlanUpdateApproval._require_scope(category, saved)

    @staticmethod
    def _targets(c, saved):
        targets = saved.snapshot.data["targets"]
        if MaintenancePlanUpdateApproval._targets_changed(c, targets):
            raise ProposalError("VERSION_CONFLICT", "Maintenance plan has changed")
        return targets

    @staticmethod
    def _apply(c, request_id, targets, executed_at):
        for target in targets:
            after = target["after"]
            updated = c.execute(
                "UPDATE maintenance_plan SET planned_start=%s,planned_end=%s,plan_status=%s,"
                "version=version+1 WHERE maintenance_plan_id=%s AND version=%s",
                (
                    after["planned_start"],
                    after["planned_end"],
                    after["plan_status"],
                    target["target_id"],
                    target["expected_version"],
                ),
            )
            if updated.rowcount != 1:
                raise ProposalError("VERSION_CONFLICT", "Maintenance plan version has changed")

    def observe_current(self, result):
        """Read the whole current plan set separately from the confirmed result."""
        targets = result["targets"]
        if not targets or any(
            t["target_type"] != "MaintenancePlan" or t["operation_type"] != "UPDATE"
            for t in targets
        ):
            raise ProposalError("INVALID_ARGUMENT", "Maintenance plan UPDATE result required")
        ids = [target["target_id"] for target in targets]
        with self.store._transaction(read_only=True) as c:
            row = c.execute(
                "SELECT statement_timestamp() AS observed_at, "
                "(SELECT jsonb_agg(to_jsonb(p) ORDER BY maintenance_plan_id) "
                "FROM (SELECT maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status,version "
                "FROM maintenance_plan WHERE maintenance_plan_id=ANY(%s::uuid[])) p) AS plans",
                (ids,),
            ).fetchone()
        plans = row["plans"] or []
        if len(plans) != len(targets):
            raise ProposalError("TARGET_NOT_FOUND", "A current plan is unavailable")
        plans = [
            {
                **p,
                "planned_start": normalize_timestamp(p["planned_start"]),
                "planned_end": normalize_timestamp(p["planned_end"]),
            }
            for p in plans
        ]
        confirmed = {t["target_id"]: t["after"]["version"] for t in targets}
        return {
            "current_snapshot": {
                "targets": [
                    {
                        "target_type": "MaintenancePlan",
                        "target_id": p["maintenance_plan_id"],
                        "snapshot": p,
                    }
                    for p in plans
                ]
            },
            "current_versions": [
                {
                    "target_type": "MaintenancePlan",
                    "target_id": p["maintenance_plan_id"],
                    "version": p["version"],
                    "confirmed_version": confirmed[p["maintenance_plan_id"]],
                    "version_delta": p["version"] - confirmed[p["maintenance_plan_id"]],
                }
                for p in plans
            ],
            "observed_at": row["observed_at"],
        }


class MaintenancePlanCreateExecute(_UpdateExecute):
    """Internal plan CREATE with fixed Snapshot IDs and DB uniqueness defense."""

    @staticmethod
    def _require_scope(saved):
        category = CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]]
        MaintenancePlanCreateApproval._require_scope(category, saved)

    @staticmethod
    def _targets(c, saved):
        targets = saved.snapshot.data["targets"]
        if MaintenancePlanCreateApproval._conflict_code(c, targets):
            raise ProposalError(
                "CREATE_CONFLICT", "Maintenance plan ID or business key already exists"
            )
        equipment_ids = sorted({t["after"]["equipment_id"] for t in targets})
        # Stabilize FK references until commit, without inventing an active-state
        # requirement or treating unrelated Equipment changes as plan conflicts.
        references = c.execute(
            "SELECT equipment_id FROM equipment WHERE equipment_id=ANY(%s::uuid[]) "
            "ORDER BY equipment_id FOR KEY SHARE",
            (equipment_ids,),
        ).fetchall()
        if {str(r["equipment_id"]) for r in references} != set(equipment_ids):
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Maintenance equipment reference is missing"
            )
        return targets

    @staticmethod
    def _apply(c, request_id, targets, executed_at):
        # CREATE has no existing row lock. Acquire unique business keys in a
        # stable order so overlapping multi-plan requests do not insert them
        # in opposite orders. Canonical Target/history order stays unchanged.
        for target in sorted(targets, key=lambda t: (t["after"]["plan_code"], t["target_id"])):
            after = target["after"]
            try:
                inserted = c.execute(
                    "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,"
                    "planned_start,planned_end,plan_status,version) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        after["maintenance_plan_id"],
                        after["plan_code"],
                        after["equipment_id"],
                        after["planned_start"],
                        after["planned_end"],
                        after["plan_status"],
                        after["version"],
                    ),
                )
            except UniqueViolation as error:
                raise ProposalError(
                    "CREATE_CONFLICT", "Maintenance plan uniqueness conflict"
                ) from error
            except ForeignKeyViolation as error:
                raise ProposalError(
                    "BUSINESS_RULE_VIOLATION", "Maintenance reference is invalid"
                ) from error
            if inserted.rowcount != 1:
                raise ProposalError("INTERNAL_ERROR", "Maintenance plan was not inserted")


class HumanExecute(_UpdateExecute):
    """Route saved Targets under the common locks, without shared mutable routing state."""

    @staticmethod
    def _require_scope(saved):
        category = CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]]
        HumanApproval._require_scope(category, saved)

    @staticmethod
    def _handler(targets):
        handlers = {
            "EquipmentState": EquipmentExecute,
            "MaintenancePlan": MaintenancePlanUpdateExecute,
        }
        if not targets or targets[0]["target_type"] not in handlers:
            raise ProposalError("INVALID_ARGUMENT", "This execution category is not supported yet")
        return handlers[targets[0]["target_type"]]

    @classmethod
    def _targets(cls, c, saved):
        return cls._handler(saved.snapshot.data["targets"])._targets(c, saved)

    @classmethod
    def _apply(cls, c, request_id, targets, executed_at):
        cls._handler(targets)._apply(c, request_id, targets, executed_at)

    def observe_current(self, result):
        return self._handler(result["targets"]).observe_current(self, result)
