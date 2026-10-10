"""Fixed execution history and state writes inside the caller transaction.

Query-only declarations mirror migrations 003/005. The service owns admission,
locks, business changes, approval consumption, Outbox, Audit and commit/rollback.
"""

from psycopg.types.json import Jsonb
from sqlalchemy import DateTime, Text, bindparam, column, func, insert, select, table, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_history = table(
    "business_update_history",
    column("history_id", UUID()),
    column("update_request_id", UUID()),
    column("approval_id", UUID()),
    column("requester_id", Text()),
    column("approver_id", Text()),
    column("category", Text()),
    column("before_snapshot", JSONB()),
    column("after_snapshot", JSONB()),
    column("result", Text()),
    column("occurred_at", DateTime(timezone=True)),
)
_request = table(
    "update_request",
    column("update_request_id", UUID()),
    column("status", Text()),
    column("execution_result", JSONB()),
    column("updated_at", DateTime(timezone=True)),
)
_approval = table(
    "approval",
    column("approval_id", UUID()),
    column("update_request_id", UUID()),
    column("approver_id", Text()),
    column("snapshot_hash", Text()),
    column("approved_at", DateTime(timezone=True)),
    column("expires_at", DateTime(timezone=True)),
    column("consumed_at", DateTime(timezone=True)),
    column("status", Text()),
    column("updated_at", DateTime(timezone=True)),
)


def insert_execution_history(
    connection,
    *,
    history_id,
    request_id,
    approval_id,
    requester_id,
    approver_id,
    category,
    before,
    after,
    executed_at,
):
    statement = insert(_history).values(
        history_id=history_id,
        update_request_id=request_id,
        approval_id=approval_id,
        requester_id=requester_id,
        approver_id=approver_id,
        category=category,
        before_snapshot=bindparam("history_before", Jsonb(before), type_=JSONB()),
        after_snapshot=bindparam("history_after", Jsonb(after), type_=JSONB()),
        result="OK",
        occurred_at=executed_at,
    )
    compiled = statement.compile(dialect=dialect())
    # compile + psycopg skips SQLAlchemy bind processors. JSON uses explicit
    # driver adaptation; UUID/text/aware timestamps are natively adapted.
    connection.execute(str(compiled), compiled.params)


def complete_execution_request(connection, *, request_id, result, consumed_at):
    statement = (
        update(_request)
        .where(_request.c.update_request_id == request_id)
        .values(
            status="COMPLETED",
            execution_result=bindparam("confirmed_result", Jsonb(result), type_=JSONB()),
            updated_at=consumed_at,
        )
    )
    compiled = statement.compile(dialect=dialect())
    # Store the confirmed result and approval consumption timestamp supplied by
    # the service; never reread current business values or observe a new clock.
    connection.execute(str(compiled), compiled.params)


def retire_execution_approval(connection, *, approval_id, status):
    if status not in {"EXPIRED", "INVALIDATED"}:
        raise ValueError("Unsupported execution retirement state")
    statement = (
        update(_approval)
        .where(_approval.c.approval_id == approval_id)
        .values(status=status, updated_at=func.clock_timestamp())
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)


def retire_execution_request(connection, *, request_id, status):
    if status not in {"EXPIRED", "INVALIDATED"}:
        raise ValueError("Unsupported execution retirement state")
    statement = (
        update(_request)
        .where(_request.c.update_request_id == request_id)
        .values(status=status, updated_at=func.clock_timestamp())
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)


def read_execution_approval(connection, request_id):
    statement = select(
        _approval.c.approver_id,
        _approval.c.snapshot_hash,
        _approval.c.approved_at,
        _approval.c.expires_at,
        _approval.c.consumed_at,
    ).where(_approval.c.update_request_id == request_id)
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()
