"""Bound Core statements; application owns transaction, authorization and locks."""

from psycopg.types.json import Jsonb
from sqlalchemy import BigInteger, DateTime, Text, column, insert, or_, select, table, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

INPUT = table(
    "maintenance_input",
    column("maintenance_input_id", UUID()),
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
    query = select(INPUT).where(INPUT.c.maintenance_input_id == identifier)
    return run(connection, query.with_for_update() if lock else query).fetchone()


def conflict(connection, after):
    return (
        run(
            connection,
            select(INPUT.c.maintenance_input_id).where(
                or_(
                    INPUT.c.maintenance_input_id == after["maintenance_input_id"],
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
            INPUT.c.maintenance_input_id == target["target_id"],
            INPUT.c.version == target["expected_version"],
        )
        .values(payload=after["payload"], version=after["version"])
    )
    return run(connection, statement).rowcount


def search(connection, filters, limit, after):
    from sqlalchemy import func

    master = table(
        "equipment",
        column("equipment_id", UUID()),
        column("equipment_code", Text()),
        column("equipment_name", Text()),
    )
    query = select(
        INPUT.c.maintenance_input_id,
        INPUT.c.input_code,
        INPUT.c.equipment_id,
        INPUT.c.version,
        master.c.equipment_code,
        master.c.equipment_name,
        func.statement_timestamp().label("_observed_at"),
    ).select_from(INPUT.join(master, INPUT.c.equipment_id == master.c.equipment_id))
    for key, value in filters.items():
        if key == "equipment_id":
            query = query.where(INPUT.c.equipment_id == value)
        elif key == "input_code":
            query = query.where(INPUT.c.input_code == value)
        elif key == "kind":
            query = query.where(INPUT.c.payload["kind"].astext == value)
        elif key == "period_start":
            query = query.where(INPUT.c.payload["period_end"].astext > value)
        elif key == "period_end":
            query = query.where(INPUT.c.payload["period_start"].astext < value)
        elif key == "equipment_query":
            query = query.where(
                or_(
                    master.c.equipment_code.contains(value, autoescape=True),
                    master.c.equipment_name.contains(value, autoescape=True),
                )
            )
    if after is not None:
        query = query.where(INPUT.c.maintenance_input_id > after)
    return run(connection, query.order_by(INPUT.c.maintenance_input_id).limit(limit + 1)).fetchall()


PLAN = table(
    "maintenance_plan",
    column("maintenance_plan_id", UUID()),
    column("equipment_id", UUID()),
    column("plan_code", Text()),
    column("plan_status", Text()),
    column("planned_start", DateTime(timezone=True)),
    column("planned_end", DateTime(timezone=True)),
)


def plan(connection, identifier, *, lock=False):
    query = select(PLAN).where(PLAN.c.maintenance_plan_id == identifier)
    return run(connection, query.with_for_update(read=True) if lock else query).fetchone()


def next_plans(connection, equipment_id, at):
    # 101 rows detect truncation; no winner is selected from an incomplete set.
    return run(
        connection,
        select(PLAN)
        .where(
            PLAN.c.equipment_id == equipment_id,
            PLAN.c.plan_status == "PLANNED",
            PLAN.c.planned_start >= at,
        )
        .order_by(PLAN.c.planned_start, PLAN.c.maintenance_plan_id)
        .limit(101),
    ).fetchall()
