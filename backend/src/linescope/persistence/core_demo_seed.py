"""Bound Core queries for fixed administrative demo fixtures, not runtime Tools."""

from sqlalchemy import Boolean, DateTime, Integer, Text, column, func, select, table, update
from sqlalchemy.dialects.postgresql import UUID, insert
from sqlalchemy.dialects.postgresql.psycopg import dialect

FIELDS = {
    "equipment": "equipment_id equipment_code equipment_name equipment_type active",
    "equipment_current_state": "equipment_id state_code",
    "process": "process_id process_code process_name active",
    "product": "product_id product_code product_name active",
    "infrastructure_resource": "infrastructure_resource_id resource_code resource_name resource_type active",
    "production_operation": "production_operation_id operation_code process_id planned_status planned_start planned_end active",
    "production_operation_equipment_assignment": "assignment_id production_operation_id equipment_id effective_from effective_to active",
    "dependency_relation": "dependency_relation_id source_entity_type source_entity_id target_entity_type target_entity_id relation_type effective_from effective_to required active",
}


def _type(name):
    if name.endswith("_id"):
        return UUID()
    if name in {"active", "required"}:
        return Boolean()
    if name.startswith(("effective_", "planned_")) and name != "planned_status":
        return DateTime(timezone=True)
    return Text()


TABLES = {
    name: table(name, *(column(field, _type(field)) for field in fields.split()))
    for name, fields in FIELDS.items()
}
CONTROL = table(
    "graph_projection_control",
    column("control_id", Integer()),
    column("rebuild_flag", Boolean()),
    column("active_generation", UUID()),
    column("fatal_error", Text()),
    column("updated_at", DateTime(timezone=True)),
)


def _execute(connection, statement):
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def insert_row(connection, name, values):
    target = TABLES[name]
    primary = next(iter(target.c))
    return (
        _execute(
            connection,
            insert(target)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[primary])
            .returning(primary),
        ).fetchone()
        is not None
    )


def read_row(connection, name, identifier):
    target = TABLES[name]
    return _execute(
        connection, select(target).where(next(iter(target.c)) == identifier).with_for_update()
    ).fetchone()


def identifiers(connection, name):
    target = TABLES[name]
    return {
        next(iter(row.values()))
        for row in _execute(connection, select(next(iter(target.c)))).fetchall()
    }


def lock_seed_control(connection):
    return _execute(
        connection, select(CONTROL).where(CONTROL.c.control_id == 1).with_for_update()
    ).fetchone()


def require_demo_rebuild(connection):
    _execute(
        connection,
        update(CONTROL)
        .where(CONTROL.c.control_id == 1)
        .values(
            fatal_error=func.coalesce(CONTROL.c.fatal_error, "DEMO_SEED_REBUILD_REQUIRED"),
            updated_at=func.statement_timestamp(),
        ),
    )
