"""Equipment-state execution and separate post-commit current-value observation."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from .audit import failed_attempt
from .canonical import normalize_uuid
from .execute_policy import ApprovalFacts, validate_new_execute
from .execution import ExecutionContext
from .logging import EventLogger, request_context
from .proposals import LOOKUP, ProposalError, ProposalStore, _saved
from .reads import json_value


class EquipmentExecute:
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
        if validate_new_execute(context, saved, facts, now=now) != "EQUIPMENT_STATE":
            raise ProposalError("INVALID_ARGUMENT", "Equipment state only")
        return now

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
            if error.code in {"VERSION_CONFLICT", "APPROVAL_EXPIRED", "APPROVAL_INVALIDATED"}:
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
            if saved.status == "COMPLETED":
                attempt["replayed"] = True
                return row["execution_result"]
            self._validate(c, context, saved, approval)
            targets = self._targets(c, saved)
            executed_at = self._validate(c, context, saved, approval)
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
                "INSERT INTO business_update_history(history_id,update_request_id,approval_id,requester_id,approver_id,category,before_snapshot,after_snapshot,result,occurred_at) VALUES(%s,%s,%s,%s,%s,'EQUIPMENT_STATE',%s,%s,'OK',%s)",
                (
                    history_id,
                    request_id,
                    saved.approval_id,
                    row["requester_id"],
                    approval["approver_id"],
                    Jsonb(snapshots[0]),
                    Jsonb(snapshots[1]),
                    executed_at,
                ),
            )
            consumed_at = self._validate(c, context, saved, approval)
            c.execute(
                "UPDATE approval SET status='CONSUMED',consumed_at=%s,updated_at=%s WHERE approval_id=%s",
                (consumed_at, consumed_at, saved.approval_id),
            )
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
            if saved.status == "COMPLETED":
                return row["execution_result"]
            if (saved.status, saved.approval_status) != ("APPROVED", "APPROVED"):
                return None
            try:
                self._validate(c, context, saved, approval)
                self._targets(c, saved)
            except ProposalError as error:
                if error.code not in {
                    "VERSION_CONFLICT",
                    "APPROVAL_EXPIRED",
                    "APPROVAL_INVALIDATED",
                }:
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
