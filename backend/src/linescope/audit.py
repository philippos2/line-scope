"""Transaction-local audit writes. No autonomous commit or public logging API."""

from uuid import uuid4

from psycopg.types.json import Jsonb


def prepare_saved(connection, context, update_request_id, approval_id, target_count):
    connection.execute(
        """INSERT INTO update_audit_event
           (audit_event_id,request_id,update_request_id,approval_id,actor_id,
            action,before_status,after_status,result_code,details,occurred_at)
           VALUES(%s,%s,%s,%s,%s,'PREPARE',NULL,'WAITING_APPROVAL','OK',%s,clock_timestamp())""",
        (
            uuid4(),
            context.request_id,
            update_request_id,
            approval_id,
            context.authenticated_user_id,
            Jsonb({"target_count": target_count}),
        ),
    )


def proposal_replaced(connection, context, previous, replacement_id):
    connection.execute(
        """INSERT INTO update_audit_event
           (audit_event_id,request_id,update_request_id,approval_id,actor_id,
            action,before_status,after_status,result_code,details,occurred_at)
           VALUES(%s,%s,%s,%s,%s,'INVALIDATE',%s,'INVALIDATED','OK',%s,clock_timestamp())""",
        (
            uuid4(),
            context.request_id,
            previous.update_request_id,
            previous.approval_id,
            context.authenticated_user_id,
            previous.status,
            Jsonb({"replacement_update_request_id": str(replacement_id)}),
        ),
    )


def failed_attempt(store, events, context, action, code, *, request_id=None, approval_id=None):
    """Best-effort separate audit after the main transaction has ended."""
    from .canonical import normalize_uuid
    from .proposals import ProposalError

    try:
        try:
            if request_id is not None:
                request_id = normalize_uuid(request_id)
            elif approval_id is not None:
                approval_id = normalize_uuid(approval_id)
            else:
                return None
        except ValueError:
            return None
        with store._transaction() as c:
            if request_id is None:
                parent = c.execute(
                    "SELECT update_request_id FROM approval WHERE approval_id=%s", (approval_id,)
                ).fetchone()
                if parent is None:
                    return None
                request_id = parent["update_request_id"]
            state = c.execute(
                "SELECT status FROM update_request WHERE update_request_id=%s FOR UPDATE",
                (request_id,),
            ).fetchone()
            if state is None:
                return None
            approval = c.execute(
                "SELECT approval_id FROM approval WHERE update_request_id=%s FOR UPDATE",
                (request_id,),
            ).fetchone()
            approval_id = approval["approval_id"] if approval else None
            c.execute(
                "INSERT INTO update_audit_event(audit_event_id,request_id,update_request_id,approval_id,actor_id,action,before_status,after_status,result_code,details,occurred_at) VALUES(%s,%s,%s,%s,%s,'FAILURE',%s,%s,%s,%s,clock_timestamp())",
                (
                    uuid4(),
                    context.request_id,
                    request_id,
                    approval_id,
                    context.authenticated_user_id,
                    state["status"],
                    state["status"],
                    code,
                    Jsonb({"attempted_action": action}),
                ),
            )
    except ProposalError:
        events.emit(
            "audit.persist_failed",
            component="audit",
            outcome="failure",
            result_code="INTERNAL_ERROR",
            level="ERROR",
            approval_id=approval_id,
            update_request_id=request_id,
        )
    return request_id
