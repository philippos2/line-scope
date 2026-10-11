"""Fixed Rebuild control transitions; caller owns short transactions."""

from sqlalchemy import Boolean, DateTime, Integer, Text, column, func, select, table, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_control = table(
    "graph_projection_control",
    column("control_id", Integer()),
    column("rebuild_flag", Boolean()),
    column("rebuild_id", UUID()),
    column("active_generation", UUID()),
    column("fatal_error", Text()),
    column("updated_at", DateTime(timezone=True)),
)
_outbox = table("graph_outbox", column("status", Text()))


def _execute(connection, statement):
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def begin_rebuild(connection, rebuild_id):
    previous = _execute(
        connection, select(_control).where(_control.c.control_id == 1).with_for_update()
    ).fetchone()
    if previous is None or previous["rebuild_flag"]:
        return None
    _execute(
        connection,
        update(_control)
        .where(_control.c.control_id == 1)
        .values(
            rebuild_flag=True,
            rebuild_id=rebuild_id,
            updated_at=func.statement_timestamp(),
        ),
    )
    return previous


def publish_rebuild(connection, ticket, generation):
    undrained = select(_outbox.c.status).where(_outbox.c.status != "APPLIED").exists()
    statement = (
        update(_control)
        .where(
            _control.c.control_id == 1,
            _control.c.rebuild_flag.is_(True),
            _control.c.rebuild_id == ticket.rebuild_id,
            _control.c.active_generation.is_not_distinct_from(ticket.previous_generation),
            ~undrained,
        )
        .values(
            active_generation=generation,
            rebuild_flag=False,
            fatal_error=None,
            updated_at=func.statement_timestamp(),
        )
    )
    return _execute(connection, statement).rowcount == 1


def fail_rebuild(connection, ticket):
    statement = (
        update(_control)
        .where(
            _control.c.control_id == 1,
            _control.c.rebuild_flag.is_(True),
            _control.c.rebuild_id == ticket.rebuild_id,
            _control.c.active_generation.is_not_distinct_from(ticket.previous_generation),
        )
        .values(
            rebuild_flag=False, fatal_error="REBUILD_FAILED", updated_at=func.statement_timestamp()
        )
    )
    return _execute(connection, statement).rowcount == 1
