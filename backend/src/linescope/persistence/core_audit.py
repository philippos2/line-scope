"""One fixed Audit INSERT, with explicit psycopg JSONB adaptation.

The caller owns authorization, event IDs, status semantics, locks and the
transaction. Query-only columns mirror migration 004 and never generate DDL.
"""

from psycopg.types.json import Jsonb
from sqlalchemy import DateTime, Text, bindparam, column, func, insert, table
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_audit = table(
    "update_audit_event",
    column("audit_event_id", UUID()),
    column("request_id", UUID()),
    column("update_request_id", UUID()),
    column("approval_id", UUID()),
    column("actor_id", Text()),
    column("action", Text()),
    column("before_status", Text()),
    column("after_status", Text()),
    column("result_code", Text()),
    column("details", JSONB()),
    column("occurred_at", DateTime(timezone=True)),
)


def insert_audit_event(
    connection,
    *,
    audit_event_id,
    request_id,
    update_request_id,
    approval_id,
    actor_id,
    action,
    before_status,
    after_status,
    result_code,
    details,
):
    statement = insert(_audit).values(
        audit_event_id=audit_event_id,
        request_id=request_id,
        update_request_id=update_request_id,
        approval_id=approval_id,
        actor_id=actor_id,
        action=action,
        before_status=before_status,
        after_status=after_status,
        result_code=result_code,
        details=bindparam("audit_details", Jsonb(details), type_=JSONB()),
        occurred_at=func.clock_timestamp(),
    )
    compiled = statement.compile(dialect=dialect())
    # This bridge does not run SQLAlchemy bind processors. Jsonb above is the
    # existing psycopg adapter; never pass an unadapted dict or serialize twice.
    # Other values use native UUID/text/NULL adaptation. No commit or new pool.
    connection.execute(str(compiled), compiled.params)
