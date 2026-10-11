"""Fixed PostgreSQL timeout reads/settings; caller owns the transaction."""

from sqlalchemy import Text, column, func, or_, select, table
from sqlalchemy.dialects.postgresql.psycopg import dialect

_settings = table(
    "pg_settings",
    column("name", Text()),
    column("setting", Text()),
    column("unit", Text()),
    schema="pg_catalog",
)
_NAMES = ("statement_timeout", "lock_timeout")


def _execute(connection, statement):
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def read_timeout_limits(connection):
    rows = _execute(
        connection,
        select(_settings).where(or_(*[_settings.c.name == name for name in _NAMES])),
    ).fetchall()
    if {row["name"] for row in rows} != set(_NAMES) or any(row["unit"] != "ms" for row in rows):
        raise ValueError("PostgreSQL timeout settings are unavailable")
    limits = {row["name"]: int(row["setting"]) for row in rows}
    if any(value < 0 for value in limits.values()):
        raise ValueError("Invalid PostgreSQL timeout settings")
    return limits


def set_local_timeout_limits(connection, *, statement_ms, lock_ms):
    if any(type(value) is not int or value <= 0 for value in (statement_ms, lock_ms)):
        raise ValueError("PostgreSQL local timeouts must be positive milliseconds")
    _execute(
        connection,
        select(
            func.pg_catalog.set_config("statement_timeout", str(statement_ms), True),
            func.pg_catalog.set_config("lock_timeout", str(lock_ms), True),
        ),
    ).fetchone()
