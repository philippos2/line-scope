"""Fixed internal Tool registry; trusted Prepare metadata is never a Tool argument.

Returns existing ReadResult / SavedProposal objects. HTTP envelope serialization,
Agent orchestration and Approval/Execute are separate responsibilities.
"""

from copy import deepcopy

from .dependency_prepare import DependencyPrepare
from .execution import ExecutionContext
from .prepare import EquipmentStatePrepare, MaintenancePrepare
from .production_prepare import ProductionPrepare
from .proposals import ProposalError
from .reads import ReadTools, ToolError

PREPARE_CATEGORIES = {
    "prepare_equipment_state_update": "EQUIPMENT_STATE",
    "prepare_maintenance_plan_create": "MAINTENANCE",
    "prepare_maintenance_plan_update": "MAINTENANCE",
    "prepare_maintenance_record_create": "MAINTENANCE",
    "prepare_production_operation_update": "PRODUCTION_OPERATION",
    "prepare_dependency_relation_update": "DEPENDENCY",
}
UUID_SCHEMA = {"type": "string", "format": "uuid"}
TIME_SCHEMA = {"type": "string", "format": "date-time"}
TEXT_SCHEMA = {"type": "string"}
BOOL_SCHEMA = {"type": "boolean"}


def _object(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "required": list(properties) if required is None else required,
    }


def _patch(properties):
    return {**_object(properties, []), "minProperties": 1}


def _single_schemas():
    state = {"type": "string", "enum": ["RUNNING", "STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"]}
    status = {"type": "string", "enum": ["PLANNED", "CANCELLED"]}
    plan = {"planned_start": TIME_SCHEMA, "planned_end": TIME_SCHEMA, "plan_status": status}
    production = {
        "planned_start": TIME_SCHEMA,
        "planned_end": TIME_SCHEMA,
        "planned_status": status,
    }
    relation = {
        "source_entity_type": {
            "type": "string",
            "enum": [
                "Equipment",
                "Process",
                "ProductionOperation",
                "Product",
                "InfrastructureResource",
            ],
        },
        "source_entity_id": UUID_SCHEMA,
        "target_entity_type": {
            "type": "string",
            "enum": [
                "Equipment",
                "Process",
                "ProductionOperation",
                "Product",
                "InfrastructureResource",
            ],
        },
        "target_entity_id": UUID_SCHEMA,
        "relation_type": {
            "type": "string",
            "enum": [
                "DEPENDS_ON",
                "PRECEDES",
                "SUPPLIES",
                "CONTROLS",
                "PRODUCES",
                "CAN_SUBSTITUTE",
            ],
        },
        "effective_from": TIME_SCHEMA,
        "effective_to": {"anyOf": [TIME_SCHEMA, {"type": "null"}]},
        "required": BOOL_SCHEMA,
        "active": BOOL_SCHEMA,
    }
    schemas = {
        "prepare_equipment_state_update": _object(
            {"equipment_id": UUID_SCHEMA, "state_code": state}
        ),
        "prepare_maintenance_plan_create": _object(
            {"plan_code": TEXT_SCHEMA, "equipment_id": UUID_SCHEMA, **plan}
        ),
        "prepare_maintenance_plan_update": _object(
            {"maintenance_plan_id": UUID_SCHEMA, "patch": _patch(plan)}
        ),
        "prepare_maintenance_record_create": _object(
            {
                "record_code": TEXT_SCHEMA,
                "equipment_id": UUID_SCHEMA,
                "performed_at": TIME_SCHEMA,
                "result": {"type": "string", "minLength": 1},
                "maintenance_plan_id": {"anyOf": [UUID_SCHEMA, {"type": "null"}]},
            },
            ["record_code", "equipment_id", "performed_at", "result"],
        ),
        "prepare_production_operation_update": {
            **_object(
                {
                    "production_operation_id": UUID_SCHEMA,
                    "patch": _patch(production),
                    "assignment_replacement": _object(
                        {
                            "effective_from": TIME_SCHEMA,
                            "effective_to": {"anyOf": [TIME_SCHEMA, {"type": "null"}]},
                            "equipment_ids": {
                                "type": "array",
                                "items": UUID_SCHEMA,
                                "uniqueItems": True,
                            },
                        }
                    ),
                },
                ["production_operation_id"],
            ),
            "anyOf": [{"required": ["patch"]}, {"required": ["assignment_replacement"]}],
        },
        "prepare_dependency_relation_update": {
            "oneOf": [
                _object({"operation_type": {"const": "CREATE"}, **relation}),
                _object(
                    {
                        "operation_type": {"const": "UPDATE"},
                        "dependency_relation_id": UUID_SCHEMA,
                        "patch": _patch(relation),
                    }
                ),
                _object(
                    {"operation_type": {"const": "DISABLE"}, "dependency_relation_id": UUID_SCHEMA}
                ),
            ]
        },
    }
    return schemas


class ToolDispatcher:
    def __init__(self, database):
        self.reads = ReadTools(database)
        self.prepares = {
            "EQUIPMENT_STATE": EquipmentStatePrepare(database),
            "MAINTENANCE": MaintenancePrepare(database),
            "PRODUCTION_OPERATION": ProductionPrepare(database),
            "DEPENDENCY": DependencyPrepare(database),
        }

    def schemas(self):
        """Advertise implemented Tools only; unknown fields are forbidden."""
        schemas = self.reads.schemas()
        singles = _single_schemas()
        for name, category in PREPARE_CATEGORIES.items():
            item_schemas = [
                _object({"prepare_tool": {"const": tool}, "input": singles[tool]})
                for tool, item_category in PREPARE_CATEGORIES.items()
                if item_category == category
            ]
            schemas[name] = {
                "oneOf": [
                    singles[name],
                    _object(
                        {
                            "targets": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"oneOf": item_schemas},
                            }
                        }
                    ),
                ],
                "description": "Single input or same-category targets; first prepare_tool must match the called Tool. Trusted identity, retry key, Agent hash and replacement ID are injected separately.",
            }
        return deepcopy(schemas)

    def run(
        self,
        context,
        tool,
        arguments,
        *,
        retry_key=None,
        agent_input_hash=None,
        supersedes_update_request_id=None,
    ):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if type(tool) is not str:
            raise ToolError("INVALID_ARGUMENT", "Tool name must be text")
        if tool not in PREPARE_CATEGORIES:
            return self.reads.run(context, tool, arguments)
        if type(arguments) is not dict:
            raise ToolError("INVALID_ARGUMENT", "Tool arguments must be an object")
        category = PREPARE_CATEGORIES[tool]
        if "targets" not in arguments:
            targets = [{"prepare_tool": tool, "input": arguments}]
        else:
            if (
                set(arguments) != {"targets"}
                or type(arguments["targets"]) is not list
                or not arguments["targets"]
            ):
                raise ToolError("INVALID_ARGUMENT", "Use single input or a nonempty targets array")
            targets = arguments["targets"]
        for target in targets:
            if (
                type(target) is not dict
                or set(target) != {"prepare_tool", "input"}
                or type(target["prepare_tool"]) is not str
                or target["prepare_tool"] not in PREPARE_CATEGORIES
                or type(target["input"]) is not dict
            ):
                raise ToolError("INVALID_ARGUMENT", "Invalid Prepare target")
        if targets[0]["prepare_tool"] != tool:
            raise ToolError("INVALID_ARGUMENT", "First target must match the called Prepare Tool")
        if any(PREPARE_CATEGORIES[target["prepare_tool"]] != category for target in targets):
            raise ToolError("BUSINESS_RULE_VIOLATION", "Prepare targets must share one category")
        values = targets if category == "MAINTENANCE" else [target["input"] for target in targets]
        try:
            return self.prepares[category].prepare(
                context,
                values,
                retry_key,
                agent_input_hash=agent_input_hash,
                supersedes_update_request_id=supersedes_update_request_id,
            )
        except ProposalError as error:
            raise ToolError(error.code, error.message) from error
