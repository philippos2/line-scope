"""Opt-in two-machine incident fixture; never resets a running demo."""

from .demo_graph_seed import END, FIXTURES, START, demo_id, endpoint, seed_graph_demo
from .demo_seed import DEMO_EQUIPMENT

EQUIPMENT = tuple(
    (identifier, code, name, "STOPPED")
    for (identifier, code, _, _), name in zip(
        DEMO_EQUIPMENT, ("第1加工機（主軸異常）", "第2加工機（冷却系異常）"), strict=True
    )
)

FIXTURES = (
    *FIXTURES,
    (
        "process",
        "P-30",
        {
            "process_id": demo_id("P-30"),
            "process_code": "P-30",
            "process_name": "第2加工工程",
            "active": True,
        },
        ("process_code", "active"),
    ),
    (
        "production_operation",
        "OP-50",
        {
            "production_operation_id": demo_id("OP-50"),
            "operation_code": "OP-50",
            "process_id": demo_id("P-30"),
            "planned_status": "PLANNED",
            "planned_start": START,
            "planned_end": END,
            "active": True,
        },
        ("operation_code", "process_id", "active"),
    ),
    (
        "product",
        "P-300",
        {
            "product_id": demo_id("P-300"),
            "product_code": "P-300",
            "product_name": "第2加工機の専用製品",
            "active": True,
        },
        ("product_code", "active"),
    ),
    (
        "production_operation_equipment_assignment",
        "USES-208",
        {
            "assignment_id": demo_id("USES-208"),
            "production_operation_id": demo_id("OP-50"),
            "equipment_id": DEMO_EQUIPMENT[1][0],
            "effective_from": START,
            "effective_to": None,
            "active": True,
        },
        None,
    ),
)

RELATIONS = (
    ("Equipment", "M-208", "Process", "P-30", "SUPPLIES", True),
    ("InfrastructureResource", "R-02", "Equipment", "M-208", "SUPPLIES", True),
    ("Process", "P-30", "Product", "P-100", "PRODUCES", False),
    ("Process", "P-30", "Product", "P-300", "PRODUCES", False),
    ("ProductionOperation", "OP-50", "Product", "P-100", "PRODUCES", False),
    ("ProductionOperation", "OP-50", "Product", "P-300", "PRODUCES", False),
)
for source_type, source, target_type, target, kind, required in RELATIONS:
    label = source + ":" + kind + ":" + target
    FIXTURES += (
        (
            "dependency_relation",
            label,
            {
                "dependency_relation_id": demo_id(label),
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
        ),
    )


def seed_incident_demo(database):
    """Bootstrap before first rebuild; retain existing names/states/versions."""
    return seed_graph_demo(database, fixtures=FIXTURES, equipment_rows=EQUIPMENT)
