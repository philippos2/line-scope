"""Fixed dependency statements, executed in the caller's mutation transaction.

Query-only columns mirror migration 002. Endpoint tables are a closed allow-list;
services retain validation, constraint deferral, write order and atomicity.
"""

from sqlalchemy import BigInteger, Boolean, DateTime, Text, column, insert, select, table, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_relation = table(
    "dependency_relation",
    column("dependency_relation_id", UUID()),
    column("source_entity_type", Text()),
    column("source_entity_id", UUID()),
    column("target_entity_type", Text()),
    column("target_entity_id", UUID()),
    column("relation_type", Text()),
    column("effective_from", DateTime(timezone=True)),
    column("effective_to", DateTime(timezone=True)),
    column("required", Boolean()),
    column("active", Boolean()),
    column("version", BigInteger()),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
)
_endpoints = {
    "Equipment": (
        table("equipment", column("equipment_id", UUID()), column("active", Boolean())),
        "equipment_id",
    ),
    "InfrastructureResource": (
        table(
            "infrastructure_resource",
            column("infrastructure_resource_id", UUID()),
            column("active", Boolean()),
        ),
        "infrastructure_resource_id",
    ),
    "Process": (
        table("process", column("process_id", UUID()), column("active", Boolean())),
        "process_id",
    ),
    "Product": (
        table("product", column("product_id", UUID()), column("active", Boolean())),
        "product_id",
    ),
    "ProductionOperation": (
        table(
            "production_operation",
            column("production_operation_id", UUID()),
            column("active", Boolean()),
        ),
        "production_operation_id",
    ),
}


def lock_dependency_endpoint(connection, kind, identifier):
    endpoint, identity = _endpoints[kind]
    statement = (
        select(endpoint.c.active)
        .where(endpoint.c[identity] == identifier)
        .with_for_update(read=True)
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchone()


def insert_dependency_relation(connection, after, executed_at):
    statement = insert(_relation).values(
        dependency_relation_id=after["dependency_relation_id"],
        source_entity_type=after["source_entity_type"],
        source_entity_id=after["source_entity_id"],
        target_entity_type=after["target_entity_type"],
        target_entity_id=after["target_entity_id"],
        relation_type=after["relation_type"],
        effective_from=after["effective_from"],
        effective_to=after["effective_to"],
        required=after["required"],
        active=after["active"],
        version=after["version"],
        created_at=executed_at,
        updated_at=executed_at,
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def update_dependency_relation(connection, target, executed_at):
    after = target["after"]
    statement = (
        update(_relation)
        .where(
            _relation.c.dependency_relation_id == target["target_id"],
            _relation.c.version == target["expected_version"],
        )
        .values(
            source_entity_type=after["source_entity_type"],
            source_entity_id=after["source_entity_id"],
            target_entity_type=after["target_entity_type"],
            target_entity_id=after["target_entity_id"],
            relation_type=after["relation_type"],
            effective_from=after["effective_from"],
            effective_to=after["effective_to"],
            required=after["required"],
            active=after["active"],
            version=after["version"],
            updated_at=executed_at,
        )
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)
