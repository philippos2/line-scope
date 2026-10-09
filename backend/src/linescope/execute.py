"""Internal equipment-state Execute. HTTP publication and observability follow."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from .canonical import normalize_uuid
from .execute_policy import ApprovalFacts, validate_new_execute
from .execution import ExecutionContext
from .proposals import LOOKUP, ProposalError, ProposalStore, _saved
from .reads import json_value


class EquipmentExecute:
    def __init__(self, database, settings):
        self.store = ProposalStore(database)
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

    def execute(self, context, request_id):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        try:
            request_id = normalize_uuid(request_id)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Valid update request ID required") from error
        try:
            return self._execute(context, request_id)
        except ProposalError as error:
            if error.code in {"VERSION_CONFLICT", "APPROVAL_EXPIRED", "APPROVAL_INVALIDATED"}:
                replay = self._retire(context, request_id)
                if replay is not None:
                    return replay
            raise

    def _execute(self, context, request_id):
        with self.store._transaction() as c:
            row, saved, approval = self._load(c, request_id)
            if row["requester_id"] != context.authenticated_user_id:
                raise ProposalError("AUTHORIZATION_DENIED", "Only requester may execute")
            if saved.status == "COMPLETED":
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
