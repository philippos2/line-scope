"""Fixed saved-target lookup and Outbox INSERT on the caller's connection.

Query-only columns mirror migrations 003/006. Validation and transaction
ownership stay in outbox.enqueue_graph_target and the Execute service.
"""

from psycopg.types.json import Jsonb
from sqlalchemy import BigInteger, Text, column, insert, select, table
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
