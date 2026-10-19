"""Regression-only fixture; never exposed as a runnable demo."""

from incident_loss_fixture import END as PERIOD_END
from incident_loss_fixture import START as PERIOD_START
from incident_loss_fixture import records
from psycopg.errors import UniqueViolation

from linescope.demo_graph_seed import END, FIXTURES, START, demo_id, endpoint, seed_graph_rows
from linescope.demo_seed import DEMO_EQUIPMENT, SeedConflict, _lock_seed
from linescope.persistence.core_demo_seed import require_demo_rebuild

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
    try:
        with database.transaction() as connection:
            control = _lock_seed(connection)
            result = seed_graph_rows(connection, FIXTURES, EQUIPMENT)
            new_inputs, retained_inputs = [], []
            for queries, target in records():
                existing = queries.read(connection, target["target_id"], lock=True)
                if existing is None:
                    queries.write(connection, target)
                    new_inputs.append(target["after"]["input_code"])
                elif any(
                    str(existing[key]) != str(target["after"][key])
                    for key in ("input_code", "equipment_id")
                ):
                    raise SeedConflict("Incident input identity conflict")
                else:
                    retained_inputs.append(existing["input_code"])
            if result["inserted"] or result["equipment"]["inserted"] or new_inputs:
                if control["active_generation"] is not None:
                    raise SeedConflict(
                        "Incident fixtures must be installed before the first Graph Rebuild"
                    )
                require_demo_rebuild(connection)
            return {
                **result,
                "registered_inputs": {"inserted": new_inputs, "retained": retained_inputs},
                "investigation": {
                    "equipment_ids": [str(row[0]) for row in EQUIPMENT],
                    "economic_input_ids": [
                        target["target_id"]
                        for queries, target in records()
                        if queries.INPUT.name == "economic_input"
                    ],
                    "period_start": PERIOD_START,
                    "period_end": PERIOD_END,
                },
            }
    except UniqueViolation as error:
        raise SeedConflict("Incident input business identity conflict") from error
