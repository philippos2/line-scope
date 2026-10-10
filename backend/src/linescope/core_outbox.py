"""Fixed saved-target lookup, enqueue and claim on the caller's connection.

Query-only columns mirror migrations 003/006. Validation and transaction
ownership stay in the calling enqueue, Execute and ProjectionQueue services.
"""

from psycopg.types.json import Jsonb
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    Text,
    and_,
    column,
    func,
    insert,
    or_,
    select,
    table,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

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
_outbox = table(
    "graph_outbox",
    column("outbox_id", UUID()),
    column("update_request_id", UUID()),
    column("update_target_id", UUID()),
    column("aggregate_type", Text()),
    column("aggregate_id", UUID()),
    column("aggregate_version", BigInteger()),
    column("event_type", Text()),
    column("payload", JSONB()),
    column("status", Text()),
    column("attempt_count", Integer()),
    column("next_attempt_at", DateTime(timezone=True)),
    column("processing_started_at", DateTime(timezone=True)),
    column("created_at", DateTime(timezone=True)),
)
_control = table(
    "graph_projection_control",
    column("control_id", Integer()),
    column("rebuild_flag", Boolean()),
)


def read_saved_graph_target(connection, request_id, target_type, target_id):
    statement = select(
        _target.c.update_target_id,
        _target.c.target_type,
        _target.c.target_id,
        _target.c.business_key,
        _target.c.operation_type,
        _target.c.before_snapshot,
        _target.c.proposed_snapshot,
        _target.c.expected_version,
    ).where(
        _target.c.update_request_id == request_id,
        _target.c.target_type == target_type,
        _target.c.target_id == target_id,
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()


def insert_graph_event(
    connection, *, outbox_id, request_id, saved_target_id, target_type, event_type, payload
):
    statement = insert(_outbox).values(
        outbox_id=outbox_id,
        update_request_id=request_id,
        update_target_id=saved_target_id,
        aggregate_type=target_type,
        aggregate_id=payload["aggregate_id"],
        aggregate_version=payload["aggregate_version"],
        event_type=event_type,
        payload=Jsonb(payload),
    )
    compiled = statement.compile(dialect=dialect())
    # Keep psycopg JSONB adaptation explicit; status/timestamps use DB defaults.
    connection.execute(str(compiled), compiled.params)


def claim_graph_event(connection):
    """One committed eligible event; lock only that event, never Graph control.

    The caller holds session leadership. This short transaction deliberately
    acquires no mutation advisory lock; application revalidation happens later.
    """
    now = func.statement_timestamp()
    dead = _outbox.alias("dead_events")
    rebuilding = select(_control.c.rebuild_flag).where(_control.c.control_id == 1).scalar_subquery()
    candidate = (
        select(_outbox.c.outbox_id)
        .where(
            or_(
                _outbox.c.status == "PENDING",
                and_(_outbox.c.status == "RETRYABLE", _outbox.c.next_attempt_at <= now),
            ),
            rebuilding.is_(False),
            ~select(dead.c.outbox_id).where(dead.c.status == "DEAD").exists(),
        )
        .order_by(_outbox.c.created_at, _outbox.c.outbox_id)
        .limit(1)
        .with_for_update()
        .cte("candidate")
    )
    statement = (
        update(_outbox)
        .where(_outbox.c.outbox_id == select(candidate.c.outbox_id).scalar_subquery())
        .values(
            status="PROCESSING",
            attempt_count=_outbox.c.attempt_count + 1,
            processing_started_at=now,
        )
        .returning(
            _outbox.c.outbox_id,
            _outbox.c.update_request_id,
            _outbox.c.update_target_id,
            _outbox.c.aggregate_type,
            _outbox.c.aggregate_id,
            _outbox.c.aggregate_version,
            _outbox.c.event_type,
            _outbox.c.payload,
            _outbox.c.attempt_count,
            _outbox.c.processing_started_at,
        )
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()
