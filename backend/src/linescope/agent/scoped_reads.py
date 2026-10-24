"""Execute a validated information plan with existing readonly Tool contracts."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from ..application.reads import ReadResult, ToolError
from .equipment_reference import question_messages

GET_ENTITY = {
    "Equipment": ("get_equipment", "equipment_id"),
    "Process": ("get_process", "process_id"),
    "Product": ("get_product", "product_id"),
    "ProductionOperation": ("get_production_operation", "production_operation_id"),
    "InfrastructureResource": ("get_infrastructure_resource", "infrastructure_resource_id"),
}
EQUIPMENT_READS = {
    "STATE": ("get_equipment_state",),
    "MAINTENANCE": ("search_maintenance_records", "search_maintenance_plans"),
    "ECONOMICS": ("search_economic_inputs",),
    "CAPACITY": ("search_capacity_inputs",),
    "SAFETY": ("search_safety_inputs",),
    "MAINTENANCE_INPUTS": ("search_maintenance_inputs",),
}
GRAPH_READS = {"UPSTREAM": "trace_upstream_dependencies", "DOWNSTREAM": "trace_downstream_impact"}


@dataclass(frozen=True)
class CollectedRead:
    tool_call_id: str
    tool: str
    result: ReadResult
    arguments: dict


def collect_scope(
    scope,
    session,
    *,
    identification_only=False,
    identified_targets=None,
    resolved_targets=None,
    selected_fields=None,
):
    observations, trace, errors = [], [], []
    targets = list(resolved_targets or ())
    available = session.schemas()

    def read(tool, arguments):
        call_id = str(uuid4())
        if tool not in available:
            errors.append(
                {
                    "code": "INVALID_ARGUMENT",
                    "message": "Requested information is unavailable",
                    "details": {},
                }
            )
            return None
        for attempt in range(3):
            if session.calls >= session.max_calls:
                errors.append(
                    {
                        "code": "AGENT_LIMIT_REACHED",
                        "message": "Read budget exhausted; results may be incomplete",
                        "details": {},
                    }
                )
                return None
            try:
                result = session.run(
                    tool, arguments, tool_call_id=call_id, attempt_count=attempt + 1
                )
                if not isinstance(result, ReadResult):
                    raise ToolError("INTERNAL_ERROR", "Invalid read result")
            except ToolError as error:
                trace.append(
                    {
                        "tool_call_id": call_id,
                        "tool": tool,
                        "attempt": attempt + 1,
                        "code": error.code,
                    }
                )
                if error.code in {"DEPENDENCY_UNAVAILABLE", "RESOURCE_BUSY"} and attempt < 2:
                    continue
                errors.append(error.as_dict())
                return None
            observations.append(CollectedRead(call_id, tool, result, arguments))
            trace.append(
                {"tool_call_id": call_id, "tool": tool, "attempt": attempt + 1, "code": "OK"}
            )
            return result
        return None

    def search(tool, filters):
        cursor, rows, seen = None, [], set()
        while True:
            arguments = {"filter": filters, "page_size": 100, "cursor": cursor}
            result = read(tool, arguments)
            if result is None:
                return rows, False
            rows.extend(result.data.get("items", []))
            cursor = result.data.get("next_cursor")
            if cursor is None:
                return rows, True
            if cursor in seen:
                errors.append(
                    {"code": "INTERNAL_ERROR", "message": "Repeated read cursor", "details": {}}
                )
                return rows, False
            seen.add(cursor)

    for subject in () if resolved_targets is not None else scope.subjects:
        kind, reference = subject["entity_type"], subject["reference"]
        if kind != "Equipment":
            try:
                identifier = str(UUID(reference))
            except ValueError:
                errors.append(
                    {
                        "code": "TARGET_AMBIGUOUS",
                        "message": "This entity requires an explicit identifier",
                        "details": {},
                    }
                )
                continue
            tool, key = GET_ENTITY[kind]
            if read(tool, {key: identifier}) is not None:
                targets.append({"entity_type": kind, "entity_id": identifier})
            continue
        matches, complete = {}, True
        queries = [("reference", reference)]
        for field, value in dict.fromkeys(queries):
            rows, finished = search("search_equipment", {field: value})
            complete = complete and finished
            for row in rows:
                if isinstance(row.get("equipment_id"), str):
                    matches[row["equipment_id"]] = row
        if complete and len(matches) == 1:
            targets.append({"entity_type": kind, "entity_id": next(iter(matches))})
        elif complete and not matches:
            errors.append(
                {
                    "code": "TARGET_NOT_FOUND",
                    "message": "No target found in completed lookup",
                    "details": {},
                }
            )
        elif len(matches) > 1:
            errors.append(
                {
                    "code": "TARGET_AMBIGUOUS",
                    "message": "Choose an equipment from the observed candidates",
                    "details": {},
                }
            )

    if identified_targets is not None:
        identified_targets.extend(targets)
    if identification_only:
        return tuple(observations), tuple(trace), tuple(errors)

    for target in targets:
        identifier = target["entity_id"]
        for topic in scope.topics:
            if target["entity_type"] == "Equipment":
                for tool in EQUIPMENT_READS.get(topic, ()):
                    if (
                        selected_fields is not None
                        and topic == "MAINTENANCE"
                        and tool
                        not in {
                            "search_maintenance_records"
                            if field == "maintenance_records"
                            else "search_maintenance_plans"
                            for field in selected_fields
                        }
                    ):
                        continue
                    if tool.startswith("search_"):
                        search(tool, {"equipment_id": identifier})
                    else:
                        read(tool, {"equipment_id": identifier})
            if topic in GRAPH_READS:
                read(GRAPH_READS[topic], {"target": target})
            if topic in {"ALTERNATIVES", "SINGLE_POINT_FAILURE"}:
                downstream = read("trace_downstream_impact", {"target": target})
                products = (
                    []
                    if downstream is None
                    else [
                        node
                        for node in downstream.data.get("reached_nodes", [])
                        if node.get("entity_type") == "Product"
                    ]
                )
                if products:
                    if topic == "ALTERNATIVES":
                        read(
                            "find_alternative_paths",
                            {"important_targets": products, "excluded_nodes": [target]},
                        )
                    else:
                        read(
                            "find_single_point_failure_candidates", {"important_targets": products}
                        )
    if "DOCUMENTS" in scope.topics:
        read(
            "retrieve_knowledge",
            {"query": question_messages(session.request.message)[-1]["content"]},
        )
    if "COMMON_DEPENDENCIES" in scope.topics and len(targets) >= 2:
        read("find_common_dependencies", {"targets": targets})
    return tuple(observations), tuple(trace), tuple(errors)
