"""Bind an explicit request time without delegating its authority to the LLM."""

from ..application.reads import ReadResult, ToolError
from ..domain.canonical import normalize_timestamp
from .graph_model_view import GRAPH_TOOLS

TEMPORAL_TOOLS = GRAPH_TOOLS | {"get_operation_equipment_assignments"}


def bind_time(tool, arguments, requested_as_of):
    if requested_as_of is None or tool not in TEMPORAL_TOOLS:
        return arguments
    if type(arguments) is not dict:
        raise ToolError("INVALID_ARGUMENT", "Tool arguments must be an object")
    if "explicit_as_of" in arguments:
        try:
            supplied = normalize_timestamp(arguments["explicit_as_of"])
        except (ValueError, TypeError) as error:
            raise ToolError("INVALID_ARGUMENT", "Invalid analysis time") from error
        if supplied != requested_as_of:
            raise ToolError("INVALID_ARGUMENT", "Tool time conflicts with the requested time")
    return {**arguments, "explicit_as_of": requested_as_of}


def time_evidence(tool, result, requested_as_of):
    if requested_as_of is None or not isinstance(result, ReadResult):
        return result
    return ReadResult(
        result.data,
        {
            **result.evidence,
            "requested_as_of": requested_as_of,
            "request_temporal_scope": (
                "CURRENT_REGISTRATION_AT_AS_OF"
                if tool in TEMPORAL_TOOLS
                else "CURRENT_STATE_AT_OBSERVATION"
            ),
        },
    )
