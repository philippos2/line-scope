"""Initial demo Graph fixtures; never production rules or approved business writes."""

from datetime import datetime, timezone
from uuid import UUID, uuid5

from psycopg.errors import UniqueViolation

from .demo_seed import DEMO_EQUIPMENT, SeedConflict, _lock_seed, _seed_equipment
from .persistence.core_demo_seed import identifiers, insert_row, read_row, require_demo_rebuild

NAMESPACE = UUID("3e31b1d7-e229-4b4e-84ea-3c01cbd54cdd")
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2027, 1, 1, tzinfo=timezone.utc)


def demo_id(label):
    return uuid5(NAMESPACE, label)


FIXTURES = []
for code in ("P-10", "P-20"):
    FIXTURES.append(
        (
            "process",
            code,
            {
                "process_id": demo_id(code),
                "process_code": code,
                "process_name": "Demo process " + code,
                "active": True,
            },
            ("process_code", "active"),
        )
    )
for code, process in (("OP-30", "P-10"), ("OP-40", "P-20")):
    FIXTURES.append(
        (
            "production_operation",
            code,
            {
                "production_operation_id": demo_id(code),
                "operation_code": code,
                "process_id": demo_id(process),
                "planned_status": "PLANNED",
                "planned_start": START,
                "planned_end": END,
                "active": True,
            },
            ("operation_code", "process_id", "active"),
        )
    )
for code in ("P-100", "P-200"):
    FIXTURES.append(
        (
            "product",
            code,
            {
                "product_id": demo_id(code),
                "product_code": code,
                "product_name": "Demo product " + code,
                "active": True,
            },
            ("product_code", "active"),
        )
    )
FIXTURES.append(
    (
        "infrastructure_resource",
        "R-02",
        {
            "infrastructure_resource_id": demo_id("R-02"),
            "resource_code": "R-02",
            "resource_name": "Demo power supply",
            "resource_type": "power",
            "active": True,
        },
        ("resource_code", "active"),
    )
)
FIXTURES.append(
    (
        "production_operation_equipment_assignment",
        "USES-204",
        {
            "assignment_id": demo_id("USES-204"),
            "production_operation_id": demo_id("OP-30"),
            "equipment_id": DEMO_EQUIPMENT[0][0],
            "effective_from": START,
            "effective_to": None,
            "active": True,
        },
        None,
    )
)


def endpoint(kind, code):
    if kind == "Equipment":
        return next(row[0] for row in DEMO_EQUIPMENT if row[1] == code)
    return demo_id(code)


RELATIONS = (
    ("Equipment", "M-204", "Process", "P-10", "SUPPLIES", True),
    ("Process", "P-10", "Process", "P-20", "PRECEDES", False),
    ("Process", "P-20", "Product", "P-100", "PRODUCES", False),
    ("Process", "P-20", "Product", "P-200", "PRODUCES", False),
    ("ProductionOperation", "OP-30", "ProductionOperation", "OP-40", "PRECEDES", False),
    ("ProductionOperation", "OP-40", "Product", "P-100", "PRODUCES", False),
    ("ProductionOperation", "OP-40", "Product", "P-200", "PRODUCES", False),
    ("InfrastructureResource", "R-02", "Equipment", "M-204", "SUPPLIES", True),
    ("Equipment", "M-208", "Equipment", "M-204", "CAN_SUBSTITUTE", False),
)
for source_type, source, target_type, target, kind, required in RELATIONS:
    code = source + ":" + kind + ":" + target
    FIXTURES.append(
        (
            "dependency_relation",
            code,
            {
                "dependency_relation_id": demo_id(code),
                "source_entity_type": source_type,
                "source_entity_id": endpoint(source_type, source),
                "target_entity_type": target_type,
                "target_entity_id": endpoint(target_type, target),
                "relation_type": kind,
                "required": required,
                "effective_from": START,
                "effective_to": None,
                "active": True,
            },
            None,
        )
    )
FIXTURES = tuple(FIXTURES)


def seed_graph_demo(database):
    """All-or-nothing initial fixture; reject other/edited relation sets.

    Matching entity identity preserves names, versions, timestamps and current
    states. Relationship semantics must match; no reset or silent repair.
    Any inserted canonical row makes the Graph unusable until explicit Rebuild.
    """
    try:
        with database.transaction() as connection:
            control = _lock_seed(connection)
            for name in ("dependency_relation", "production_operation_equipment_assignment"):
                expected = {
                    next(iter(row.values())) for table, _, row, _ in FIXTURES if table == name
                }
                if identifiers(connection, name) - expected:
                    raise SeedConflict("Graph demo seed is limited to an initial demo relation set")
            equipment = _seed_equipment(connection)
            for equipment_id, code, _, _ in DEMO_EQUIPMENT:
                if not read_row(connection, "equipment", equipment_id)["active"]:
                    raise SeedConflict(f"Demo Graph equipment is inactive: {code}")
            inserted, retained = [], []
            for table, label, row, identity in FIXTURES:
                if insert_row(connection, table, row):
                    inserted.append(label)
                else:
                    existing = read_row(connection, table, next(iter(row.values())))
                    fields = identity or tuple(row)
                    if existing is None or any(existing[field] != row[field] for field in fields):
                        raise SeedConflict(f"Demo Graph identity or relation conflict: {label}")
                    retained.append(label)
            if inserted or equipment["inserted"]:
                if control["active_generation"] is not None:
                    raise SeedConflict(
                        "New demo rows require seeding before the first Graph Rebuild"
                    )
                require_demo_rebuild(connection)
            return {"equipment": equipment, "inserted": inserted, "retained": retained}
    except UniqueViolation as error:
        raise SeedConflict("Demo Graph business identity is already in use") from error
