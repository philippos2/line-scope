"""Fixed Core statements for human approval locks and state updates.

Query-only column declarations mirror migration 003, never generate DDL, and
do not model the complete tables. The human service owns authorization, locks,
audit and commit/rollback. This is not a generic Core write executor.
"""

from datetime import timedelta

from sqlalchemy import DateTime, Text, bindparam, column, func, select, table, update
from sqlalchemy.dialects.postgresql import INTERVAL, UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_approval = table(
    "approval",
    column("approval_id", UUID()),
    column("update_request_id", UUID()),
    column("approver_id", Text()),
    column("status", Text()),
    column("updated_at", DateTime(timezone=True)),
    column("approved_at", DateTime(timezone=True)),
    column("expires_at", DateTime(timezone=True)),
)
_request = table(
    "update_request",
    column("update_request_id", UUID()),
    column("status", Text()),
    column("updated_at", DateTime(timezone=True)),
)


def reject_proposal_state(connection, approval_id, request_id, actor_id):
    """Preserve the two UPDATEs and their order; never commit or acquire a connection."""
    approval = (
        update(_approval)
        .where(_approval.c.approval_id == approval_id)
        .values(status="REJECTED", approver_id=actor_id, updated_at=func.clock_timestamp())
    )
    request = (
        update(_request)
        .where(_request.c.update_request_id == request_id)
        .values(status="REJECTED", updated_at=func.clock_timestamp())
    )
    for statement in (approval, request):
        compiled = statement.compile(dialect=dialect())
        # Values are UUID/text only, natively adapted by psycopg. No JSON/custom
        # type processing or SQLAlchemy Engine/autobegin is introduced here.
        connection.execute(str(compiled), compiled.params)


def approve_proposal_state(connection, approval_id, request_id, actor_id):
    """Set one server observation and return its exact 30-minute deadline."""
    now = select(func.clock_timestamp().label("approved_at")).cte("now")
    statement = (
        update(_approval)
        .where(_approval.c.approval_id == approval_id)
        .values(
            status="APPROVED",
            approver_id=actor_id,
            approved_at=now.c.approved_at,
            expires_at=now.c.approved_at
            + bindparam("approval_lifetime", timedelta(minutes=30), type_=INTERVAL()),
            updated_at=now.c.approved_at,
        )
        .returning(_approval.c.approved_at, _approval.c.expires_at)
    )
    compiled = statement.compile(dialect=dialect())
    # psycopg natively adapts timedelta to PostgreSQL interval, and dict_row
    # returns aware timestamps. The volatile clock CTE matches the existing SQL.
    times = connection.execute(str(compiled), compiled.params).fetchone()
    _finish_approve_request(connection, request_id, "APPROVED")
    return times


def invalidate_proposal_state(connection, approval_id, request_id):
    """Maintain both state updates before the caller's INVALIDATE audit/commit."""
    statement = (
        update(_approval)
        .where(_approval.c.approval_id == approval_id)
        .values(status="INVALIDATED", updated_at=func.clock_timestamp())
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)
    _finish_approve_request(connection, request_id, "INVALIDATED")


def _finish_approve_request(connection, request_id, status):
    if status not in {"APPROVED", "INVALIDATED"}:
        raise ValueError("Unsupported human approval transition")
    statement = (
        update(_request)
        .where(_request.c.update_request_id == request_id)
        .values(status=status, updated_at=func.clock_timestamp())
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)


def find_approval_parent(connection, approval_id):
    statement = select(_approval.c.update_request_id).where(_approval.c.approval_id == approval_id)
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()


def lock_update_request(connection, request_id):
    statement = (
        select(_request.c.update_request_id)
        .where(_request.c.update_request_id == request_id)
        .with_for_update()
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()


def lock_approval(connection, approval_id, request_id):
    statement = (
        select(_approval.c.approval_id)
        .where(
            _approval.c.approval_id == approval_id,
            _approval.c.update_request_id == request_id,
        )
        .with_for_update()
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()
