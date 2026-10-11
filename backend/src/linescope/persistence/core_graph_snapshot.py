"""One fixed Core SELECT for all Graph source records on the caller connection.

Declarations mirror migration 002. No active/time filter: disabled and expired
edges are retained for rebuild markers and registered-history analysis.
"""

from sqlalchemy import column, func, literal, select, table, true, union_all
from sqlalchemy.dialects.postgresql.psycopg import dialect

NODE_TABLES = (
    ("Equipment", "equipment", "equipment_id"),
    ("Process", "process", "process_id"),
    ("ProductionOperation", "production_operation", "production_operation_id"),
    ("Product", "product", "product_id"),
    ("InfrastructureResource", "infrastructure_resource", "infrastructure_resource_id"),
)
EDGE_TABLES = (
    (
        "DependencyRelation",
        "dependency_relation",
        "dependency_relation_id",
        (
            "dependency_relation_id",
            "version",
            "source_entity_type",
            "source_entity_id",
            "target_entity_type",
            "target_entity_id",
            "relation_type",
            "effective_from",
            "effective_to",
            "required",
            "active",
        ),
    ),
    (
        "ProductionOperationEquipmentAssignment",
        "production_operation_equipment_assignment",
        "assignment_id",
        (
            "assignment_id",
            "version",
            "production_operation_id",
            "equipment_id",
            "effective_from",
            "effective_to",
            "active",
        ),
    ),
)


def _object(fields):
    return func.jsonb_build_object(*[item for key, value in fields for item in (key, value)])


def graph_snapshot_rows(connection):
    branches = []
    for kind, name, key in NODE_TABLES:
        source = table(name, *[column(field) for field in (key, "version", "active")])
        branches.append(
            select(
                literal("NODE").label("category"),
                literal(kind).label("kind"),
                source.c[key].label("identifier"),
                _object(
                    (
                        ("entity_type", kind),
                        ("entity_id", source.c[key]),
                        ("entity_version", source.c.version),
                        ("active", source.c.active),
                    )
                ).label("data"),
            )
        )
    for kind, name, key, fields in EDGE_TABLES:
        source = table(name, *[column(field) for field in fields])
        branches.append(
            select(
                literal("AGGREGATE"),
                literal(kind),
                source.c[key],
                _object(tuple((field, source.c[field]) for field in fields)),
            )
        )
    records = union_all(*branches).subquery("records")
    observation = select(true().label("present")).subquery("observation")
    statement = (
        select(func.statement_timestamp().label("observed_at"), records)
        .select_from(observation.outerjoin(records, true()))
        .order_by(records.c.category, records.c.kind, records.c.identifier)
    )
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params).fetchall()
