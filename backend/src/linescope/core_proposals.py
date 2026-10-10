"""Fixed proposal storage statements; admission and transactions stay in service.

Query-only columns mirror migration 003. No DDL, independent connection,
commit, canonicalization or retry decision is performed here.
"""

from psycopg.types.json import Jsonb
from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    Text,
    bindparam,
    column,
    func,
    select,
    table,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.dialects.postgresql.psycopg import dialect

_request = table(
    "update_request",
    column("update_request_id", UUID()),
    column("requester_id", Text()),
    column("operation_type", Text()),
    column("status", Text()),
    column("idempotency_key", UUID()),
    column("prepare_retry_key", UUID()),
    column("prepare_input_hash", Text()),
    column("agent_input_hash", Text()),
    column("canonical_snapshot", Text()),
    column("snapshot_schema_version", Integer()),
    column("snapshot_hash", Text()),
    column("updated_at", DateTime(timezone=True)),
)
_target = table(
    "update_target",
    column("update_target_id", UUID()),
    column("update_request_id", UUID()),
    column("target_type", Text()),
    column("target_id", UUID()),
    column("business_key", JSONB()),
    column("operation_type", Text()),
    column("before_snapshot", JSONB()),
    column("proposed_snapshot", JSONB()),
    column("expected_version", BigInteger()),
)
_approval = table(
    "approval",
    column("approval_id", UUID()),
    column("update_request_id", UUID()),
    column("status", Text()),
    column("snapshot_hash", Text()),
    column("updated_at", DateTime(timezone=True)),
)


def insert_pending_request(
    connection,
    *,
    request_id,
    requester_id,
    operation_type,
    idempotency_key,
    retry_key,
    prepare_input_hash,
    agent_input_hash,
    snapshot,
):
    statement = (
        insert(_request)
        .values(
            update_request_id=request_id,
            requester_id=requester_id,
            operation_type=operation_type,
            status="WAITING_APPROVAL",
            idempotency_key=idempotency_key,
            prepare_retry_key=retry_key,
            prepare_input_hash=prepare_input_hash,
            agent_input_hash=agent_input_hash,
            canonical_snapshot=snapshot.canonical_text,
            snapshot_schema_version=1,
            snapshot_hash=snapshot.snapshot_hash,
        )
        .on_conflict_do_nothing(
            index_elements=[_request.c.requester_id, _request.c.prepare_retry_key]
        )
        .returning(_request.c.update_request_id)
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()


def insert_proposal_target(connection, *, target_row_id, request_id, target):
    # compile + psycopg does not invoke SQLAlchemy bind processors. Preserve
    # explicit Jsonb adaptation, especially SQL NULL (not JSON null) for CREATE.
    before = Jsonb(target["before"]) if target["before"] is not None else None
    statement = insert(_target).values(
        update_target_id=target_row_id,
        update_request_id=request_id,
        target_type=target["target_type"],
        target_id=target["target_id"],
        business_key=bindparam("target_business_key", Jsonb(target["business_key"]), type_=JSONB()),
        operation_type=target["operation_type"],
        before_snapshot=bindparam("target_before", before, type_=JSONB()),
        proposed_snapshot=bindparam("target_after", Jsonb(target["after"]), type_=JSONB()),
        expected_version=target["expected_version"],
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)


def insert_pending_approval(connection, *, approval_id, request_id, snapshot_hash):
    statement = insert(_approval).values(
        approval_id=approval_id,
        update_request_id=request_id,
        status="PENDING",
        snapshot_hash=snapshot_hash,
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)


def lock_replaced_request(connection, request_id):
    statement = (
        select(_request.c.requester_id, _request.c.prepare_retry_key)
        .where(_request.c.update_request_id == request_id)
        .with_for_update()
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()


def lock_replaced_approval(connection, request_id):
    statement = (
        select(_approval.c.approval_id)
        .where(_approval.c.update_request_id == request_id)
        .with_for_update()
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()


def invalidate_replaced_request(connection, request_id):
    statement = (
        update(_request)
        .where(_request.c.update_request_id == request_id)
        .values(status="INVALIDATED", updated_at=func.clock_timestamp())
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)


def invalidate_replaced_approval(connection, request_id):
    statement = (
        update(_approval)
        .where(_approval.c.update_request_id == request_id)
        .values(status="INVALIDATED", updated_at=func.clock_timestamp())
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)
