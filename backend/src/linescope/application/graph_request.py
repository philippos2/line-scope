"""Validate ordinary Graph traversal before opening any storage connection.

Internal request policy, not Tool publication or an existence/active check.
Trusted identity, time and system limits are supplied by the application.
"""

from dataclasses import dataclass
from datetime import datetime

from ..domain.canonical import normalize_timestamp, normalize_uuid
from ..domain.graph_traversal import IMPACT_FORWARD, IMPACT_REVERSE
from ..execution import ExecutionContext
from .reads import ToolError

ENTITY_TYPES = frozenset(
    {"Equipment", "Process", "ProductionOperation", "Product", "InfrastructureResource"}
)
TOOLS = {"trace_downstream_impact": "IMPACT", "trace_upstream_dependencies": "UPSTREAM"}
LIMIT_NAMES = ("max_depth", "max_nodes", "max_paths")


@dataclass(frozen=True)
class GraphLimits:
    max_depth: int
    max_nodes: int
    max_paths: int
    timeout_ms: int

    def __post_init__(self):
        for value in (self.max_depth, self.max_nodes, self.max_paths, self.timeout_ms):
            if type(value) is not int or value <= 0:
                raise ValueError("Server Graph limits must be positive integers")


@dataclass(frozen=True)
class GraphRequest:
    tool: str
    direction: str
    target: tuple[str, str]
    as_of: datetime
    relation_types: tuple[str, ...]
    requested_limits: tuple[tuple[str, int], ...]
    effective_limits: GraphLimits


def validate_graph_request(context, tool, arguments, *, system_limits, server_time):
    """Authenticate/authorize independently of untrusted Tool arguments.

    One immutable server time is used for default as_of and future rejection.
    Requested depth/nodes/paths can only lower the corresponding system limit.
    Timeout has no client-controlled field. Unknown tools/fields fail closed.
    """
    if not isinstance(context, ExecutionContext):
        raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
    if context.role not in {"maintenance", "production", "manager"}:
        raise ToolError("AUTHORIZATION_DENIED", "Graph analysis permission is required")
    if not isinstance(system_limits, GraphLimits):
        raise ValueError("Server Graph limits are required")
    if not isinstance(server_time, datetime):
        raise ValueError("Server analysis time is required")
    observed = datetime.fromisoformat(normalize_timestamp(server_time))
    try:
        fields = {"target", "relation_types", "explicit_as_of"} | {
            "requested_" + name for name in LIMIT_NAMES
        }
        if type(tool) is not str or tool not in TOOLS:
            raise ValueError("Unknown traversal Tool")
        if type(arguments) is not dict or set(arguments) - fields:
            raise ValueError("Invalid Graph fields")
        target = arguments.get("target")
        if type(target) is not dict or set(target) != {"entity_type", "entity_id"}:
            raise ValueError("Typed target is required")
        entity_type = target["entity_type"]
        if type(entity_type) is not str or entity_type not in ENTITY_TYPES:
            raise ValueError("Invalid Graph target type")
        if type(target["entity_id"]) is not str:
            raise ValueError("Tool target ID must be a string")
        entity_id = normalize_uuid(target["entity_id"])
        if "explicit_as_of" in arguments and type(arguments["explicit_as_of"]) is not str:
            raise ValueError("Tool analysis time must be a string")
        as_of = (
            datetime.fromisoformat(normalize_timestamp(arguments["explicit_as_of"]))
            if "explicit_as_of" in arguments
            else observed
        )
        if as_of > observed:
            raise ValueError("Future analysis time is not permitted")
        allowed_relations = IMPACT_FORWARD | IMPACT_REVERSE
        relations = arguments.get("relation_types", sorted(allowed_relations))
        if (
            type(relations) is not list
            or not relations
            or any(type(item) is not str or item not in allowed_relations for item in relations)
        ):
            raise ValueError("Invalid ordinary traversal relation filter")
        requested, effective = [], {}
        for name in LIMIT_NAMES:
            key = "requested_" + name
            if key in arguments:
                value = arguments[key]
                if type(value) is not int or value <= 0:
                    raise ValueError("Requested limits must be positive integers")
                requested.append((name, value))
                effective[name] = min(value, getattr(system_limits, name))
            else:
                effective[name] = getattr(system_limits, name)
        limits = GraphLimits(**effective, timeout_ms=system_limits.timeout_ms)
    except (ValueError, TypeError) as error:
        raise ToolError("INVALID_ARGUMENT", "Invalid Graph traversal request") from error
    return GraphRequest(
        tool,
        TOOLS[tool],
        (entity_type, entity_id),
        as_of,
        tuple(sorted(set(relations))),
        tuple(requested),
        limits,
    )
