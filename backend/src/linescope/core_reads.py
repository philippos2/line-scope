"""Core-built single-record SELECTs, executed on the caller's psycopg transaction.

These query-only declarations mirror migration 002; they never create schema.
The bridge is deliberately limited to the fixed UUID-bound reads. It does not supply
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
_plan = table(
    "maintenance_plan",
    column("maintenance_plan_id", PGUUID()),
    column("version", BigInteger()),
    column("plan_code", Text()),
    column("equipment_id", PGUUID()),
    column("planned_start", DateTime(timezone=True)),
    column("planned_end", DateTime(timezone=True)),
    column("plan_status", Text()),
)
_process = table(
    "process",
    column("process_id", PGUUID()),
    column("version", BigInteger()),
    column("process_code", Text()),
    column("process_name", Text()),
    column("active", Boolean()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_operation = table(
    "production_operation",
    column("production_operation_id", PGUUID()),
    column("version", BigInteger()),
    column("operation_code", Text()),
    column("process_id", PGUUID()),
    column("planned_status", Text()),
    column("planned_start", DateTime(timezone=True)),
    column("planned_end", DateTime(timezone=True)),
    column("active", Boolean()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_product = table(
    "product",
    column("product_id", PGUUID()),
    column("version", BigInteger()),
    column("product_code", Text()),
    column("product_name", Text()),
    column("active", Boolean()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_resource = table(
    "infrastructure_resource",
    column("infrastructure_resource_id", PGUUID()),
    column("version", BigInteger()),
    column("resource_code", Text()),
    column("resource_name", Text()),
    column("resource_type", Text()),
    column("active", Boolean()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_relation = table(
    "dependency_relation",
    column("dependency_relation_id", PGUUID()),
    column("version", BigInteger()),
    column("source_entity_type", Text()),
    column("source_entity_id", PGUUID()),
    column("target_entity_type", Text()),
    column("target_entity_id", PGUUID()),
    column("relation_type", Text()),
    column("effective_from", DateTime(timezone=True)),
    column("effective_to", DateTime(timezone=True)),
    column("required", Boolean()),
    column("active", Boolean()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_tables = {
    "get_equipment": (_equipment, "equipment_id"),
    "get_equipment_state": (_state, "equipment_id"),
    "get_maintenance_plan": (_plan, "maintenance_plan_id"),
    "get_process": (_process, "process_id"),
    "get_production_operation": (_operation, "production_operation_id"),
    "get_product": (_product, "product_id"),
    "get_infrastructure_resource": (_resource, "infrastructure_resource_id"),
    "get_dependency_relation": (_relation, "dependency_relation_id"),
}


def get_record_row(connection, tool: str, identifier: UUID):
    """Use a fixed tool allow-list and bound UUID; leave transaction ownership intact."""
    target, key = _tables[tool]
    statement = select(target, func.statement_timestamp().label("_observed_at")).where(
        target.c[key] == identifier
    )
    compiled = statement.compile(dialect=dialect())
    # Never interpolate compiled.params or enable literal_binds. psycopg adapts
    # UUID and decodes the native result types using the existing dict_row factory.
    return connection.execute(str(compiled), compiled.params).fetchone()
