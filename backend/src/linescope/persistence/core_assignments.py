"""Fixed assignment statements on the caller's transaction; no workflow ownership.

Query-only columns mirror migrations 002/003. The service owns coordination,
interval validation, write order, version conflicts and history/Outbox atomicity.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Text,
    bindparam,
    column,
    insert,
    select,
    table,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_assignment = table(
    "production_operation_equipment_assignment",
    column("assignment_id", UUID()),
    column("production_operation_id", UUID()),
    column("equipment_id", UUID()),
    column("effective_from", DateTime(timezone=True)),
    column("effective_to", DateTime(timezone=True)),
    column("active", Boolean()),
    column("version", BigInteger()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_target = table(
    "update_target",
    column("update_request_id", UUID()),
    column("target_type", Text()),
)
_equipment = table("equipment", column("equipment_id", UUID()))


def request_changes_assignments(connection, request_id):
    statement = select(
        select(_target.c.update_request_id)
        .where(
            _target.c.update_request_id == request_id,
            _target.c.target_type == "ProductionOperationEquipmentAssignment",
        )
        .exists()
        .label("changed")
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()["changed"]


def lock_assignment_equipment(connection, equipment_ids):
    statement = (
        select(_equipment.c.equipment_id)
        .where(
            _equipment.c.equipment_id
            == bindparam("equipment_ids", equipment_ids, type_=ARRAY(UUID())).any_()
        )
        .order_by(_equipment.c.equipment_id)
        .with_for_update(read=True)
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchall()


def insert_assignment(connection, after, executed_at):
    statement = insert(_assignment).values(
        assignment_id=after["assignment_id"],
        production_operation_id=after["production_operation_id"],
        equipment_id=after["equipment_id"],
        effective_from=after["effective_from"],
        effective_to=after["effective_to"],
        active=after["active"],
        version=after["version"],
        created_at=executed_at,
        updated_at=executed_at,
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def update_assignment(connection, target, executed_at):
    # Immutable operation/equipment/start keys are never part of this UPDATE.
    after = target["after"]
    statement = (
        update(_assignment)
        .where(
            _assignment.c.assignment_id == target["target_id"],
            _assignment.c.version == target["expected_version"],
        )
        .values(
            effective_to=after["effective_to"],
            active=after["active"],
            version=_assignment.c.version + 1,
            updated_at=executed_at,
        )
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)
