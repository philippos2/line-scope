"""Normalize demo inputs through domain contracts."""

from .demo_graph_seed import demo_id
from .domain import capacity, economics, maintenance_inputs, safety
from .persistence import core_capacity, core_economics, core_maintenance_inputs, core_safety


def make_record(kind, code, equipment_id, payload, **extra):
    module, queries = {
        "economic": (economics, core_economics),
        "capacity": (capacity, core_capacity),
        "safety": (safety, core_safety),
        "maintenance": (maintenance_inputs, core_maintenance_inputs),
    }[kind]
    key = "maintenance_input_id" if kind == "maintenance" else kind + "_input_id"
    after = module.normalize_record(
        {
            key: str(demo_id(code)),
            "input_code": code,
            "equipment_id": equipment_id,
            "payload": payload,
            "version": 1,
            **extra,
        }
    )
    return queries, {"target_id": after[key], "operation_type": "CREATE", "after": after}
