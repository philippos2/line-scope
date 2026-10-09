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
