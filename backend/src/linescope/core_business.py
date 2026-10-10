"""Fixed equipment, schedule and maintenance writes on the caller connection.

Query-only columns mirror migrations 002/005. The service validates canonical
targets, owns locks/order and interprets rowcount/DB errors inside its transaction.
"""

from sqlalchemy import BigInteger, DateTime, Text, column, insert, table, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_state = table(
    "equipment_current_state",
    column("equipment_id", UUID()),
    column("state_code", Text()),
    column("version", BigInteger()),
    column("updated_at", DateTime(timezone=True)),
)
_state_history = table(
    "equipment_state_history",
    column("history_id", UUID()),
    column("equipment_id", UUID()),
    column("update_request_id", UUID()),
    column("state_code", Text()),
    column("effective_at", DateTime(timezone=True)),
    column("recorded_at", DateTime(timezone=True)),
)
_operation = table(
    "production_operation",
    column("production_operation_id", UUID()),
    column("planned_start", DateTime(timezone=True)),
    column("planned_end", DateTime(timezone=True)),
    column("planned_status", Text()),
    column("version", BigInteger()),
    column("updated_at", DateTime(timezone=True)),
)
_plan = table(
    "maintenance_plan",
    column("maintenance_plan_id", UUID()),
    column("plan_code", Text()),
    column("equipment_id", UUID()),
    column("planned_start", DateTime(timezone=True)),
    column("planned_end", DateTime(timezone=True)),
    column("plan_status", Text()),
    column("version", BigInteger()),
)
_record = table(
    "maintenance_record",
    column("maintenance_record_id", UUID()),
    column("record_code", Text()),
    column("equipment_id", UUID()),
    column("performed_at", DateTime(timezone=True)),
    column("result", Text()),
    column("maintenance_plan_id", UUID()),
    column("version", BigInteger()),
)


def update_equipment_state(connection, target, executed_at):
    statement = (
        update(_state)
        .where(
            _state.c.equipment_id == target["target_id"],
            _state.c.version == target["expected_version"],
        )
        .values(
            state_code=target["after"]["state_code"],
            version=_state.c.version + 1,
            updated_at=executed_at,
        )
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def insert_equipment_state_history(connection, *, history_id, request_id, target, executed_at):
    statement = insert(_state_history).values(
        history_id=history_id,
        equipment_id=target["target_id"],
        update_request_id=request_id,
        state_code=target["after"]["state_code"],
        effective_at=executed_at,
        recorded_at=executed_at,
    )
    compiled = statement.compile(dialect=dialect())
    connection.execute(str(compiled), compiled.params)


def update_production_schedule(connection, target, executed_at):
    after = target["after"]
    statement = (
        update(_operation)
        .where(
            _operation.c.production_operation_id == target["target_id"],
            _operation.c.version == target["expected_version"],
        )
        .values(
            planned_start=after["planned_start"],
            planned_end=after["planned_end"],
            planned_status=after["planned_status"],
            updated_at=executed_at,
            version=_operation.c.version + 1,
        )
    )
    compiled = statement.compile(dialect=dialect())
    # Canonical UTC strings retain the existing psycopg/server timestamp
    # adaptation; no SQLAlchemy bind processor or new datetime interpretation.
    return connection.execute(str(compiled), compiled.params)


def update_maintenance_plan(connection, target):
    after = target["after"]
    statement = (
        update(_plan)
        .where(
            _plan.c.maintenance_plan_id == target["target_id"],
            _plan.c.version == target["expected_version"],
        )
        .values(
            planned_start=after["planned_start"],
            planned_end=after["planned_end"],
            plan_status=after["plan_status"],
            version=_plan.c.version + 1,
        )
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def insert_maintenance_plan(connection, after):
    statement = insert(_plan).values(
        maintenance_plan_id=after["maintenance_plan_id"],
        plan_code=after["plan_code"],
        equipment_id=after["equipment_id"],
        planned_start=after["planned_start"],
        planned_end=after["planned_end"],
        plan_status=after["plan_status"],
        version=after["version"],
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def insert_maintenance_record(connection, after):
    statement = insert(_record).values(
        maintenance_record_id=after["maintenance_record_id"],
        record_code=after["record_code"],
        equipment_id=after["equipment_id"],
        performed_at=after["performed_at"],
        result=after["result"],
        maintenance_plan_id=after["maintenance_plan_id"],
        version=after["version"],
    )
    compiled = statement.compile(dialect=dialect())
    # NULL plan IDs stay SQL NULL; allowed result text is always a bound value.
    return connection.execute(str(compiled), compiled.params)
