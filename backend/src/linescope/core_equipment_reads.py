"""Core-built equipment SELECTs, executed on the caller's psycopg transaction.

These query-only declarations mirror migration 002; they never create schema.
The bridge is deliberately limited to these UUID-bound reads. It does not supply
SQLAlchemy execution/type processing for arbitrary statements or write paths.
"""

from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Text, column, func, select, table
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_equipment = table(
    "equipment",
    column("equipment_id", PGUUID()),
    column("version", BigInteger()),
    column("equipment_code", Text()),
    column("equipment_name", Text()),
    column("equipment_type", Text()),
    column("active", Boolean()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_state = table(
    "equipment_current_state",
    column("equipment_id", PGUUID()),
    column("version", BigInteger()),
    column("state_code", Text()),
    column("updated_at", DateTime(timezone=True)),
)
_tables = {"get_equipment": _equipment, "get_equipment_state": _state}


def get_equipment_row(connection, tool: str, equipment_id: UUID):
    """Use a fixed tool allow-list and bound UUID; leave transaction ownership intact."""
    target = _tables[tool]
    statement = select(target, func.statement_timestamp().label("_observed_at")).where(
        target.c.equipment_id == equipment_id
    )
    compiled = statement.compile(dialect=dialect())
    # Never interpolate compiled.params or enable literal_binds. psycopg adapts
    # UUID and decodes the native result types using the existing dict_row factory.
    return connection.execute(str(compiled), compiled.params).fetchone()
