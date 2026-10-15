"""Bound Core statements; application owns transaction, authorization and locks."""

from psycopg.types.json import Jsonb
from sqlalchemy import BigInteger, Text, column, insert, or_, select, table, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

INPUT = table(
    "economic_input",
    column("economic_input_id", UUID()),
    column("input_code", Text()),
    column("equipment_id", UUID()),
    column("payload", JSONB()),
    column("version", BigInteger()),
)
EQUIPMENT = table("equipment", column("equipment_id", UUID()))


def run(connection, statement):
    compiled = statement.compile(dialect=dialect())
    # psycopg executes compiled Core directly: adapt JSONB explicitly.
    params = {
        key: Jsonb(value) if type(value) is dict else value
        for key, value in compiled.params.items()
    }
    return connection.execute(str(compiled), params)


def read(connection, identifier, *, lock=False):
    query = select(INPUT).where(INPUT.c.economic_input_id == identifier)
    return run(connection, query.with_for_update() if lock else query).fetchone()


def conflict(connection, after):
    return (
        run(
            connection,
            select(INPUT.c.economic_input_id).where(
                or_(
                    INPUT.c.economic_input_id == after["economic_input_id"],
                    INPUT.c.input_code == after["input_code"],
                )
            ),
        ).fetchone()
        is not None
    )


def equipment(connection, identifier, *, lock=False):
    query = select(EQUIPMENT.c.equipment_id).where(EQUIPMENT.c.equipment_id == identifier)
    # SQLAlchemy read=True/key_share=True renders PostgreSQL FOR KEY SHARE.
    return (
        run(
            connection, query.with_for_update(read=True, key_share=True) if lock else query
        ).fetchone()
        is not None
    )


def write(connection, target):
    after = target["after"]
    statement = (
        insert(INPUT).values(**after)
        if target["operation_type"] == "CREATE"
        else update(INPUT)
        .where(
            INPUT.c.economic_input_id == target["target_id"],
            INPUT.c.version == target["expected_version"],
        )
        .values(payload=after["payload"], version=after["version"])
    )
    return run(connection, statement).rowcount
