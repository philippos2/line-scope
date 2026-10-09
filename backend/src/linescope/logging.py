"""Allowlisted operational events. Business audit persistence is separate."""

import json
import logging
import re
import sys
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
EVENTS = {
    "service.started",
    "service.stopped",
    "http.request.completed",
    "tool.call.completed",
    "proposal.saved",
    "proposal.replayed",
    "proposal.replaced",
    "approval.completed",
    "execute.completed",
    "execution.outcome_unknown",
    "projection.attempt.completed",
    "projection.retry_scheduled",
    "projection.dead",
    "rebuild.started",
    "rebuild.completed",
    "rebuild.failed",
    "audit.persist_failed",
    "runtime.diagnostic",
}
CODES = {
    "OK",
    "AUTHENTICATION_REQUIRED",
    "AUTHORIZATION_DENIED",
    "HTTP_ERROR",
    "INVALID_ARGUMENT",
    "DEPENDENCY_UNAVAILABLE",
    "INTERNAL_ERROR",
    "RESOURCE_BUSY",
    "REQUEST_ABORTED",
    "RUNTIME_WARNING",
    "RUNTIME_ERROR",
    "TARGET_NOT_FOUND",
    "TARGET_AMBIGUOUS",
    "MISSING_REQUIRED_ARGUMENT",
    "APPROVAL_REQUIRED",
    "APPROVAL_MISMATCH",
    "APPROVAL_EXPIRED",
    "APPROVAL_INVALIDATED",
    "APPROVAL_ALREADY_CONSUMED",
    "INVALID_UPDATE_STATE",
    "VERSION_CONFLICT",
    "CREATE_CONFLICT",
    "DUPLICATE_REQUEST",
    "BUSINESS_RULE_VIOLATION",
    "UPDATE_FAILED",
    "GRAPH_NOT_CURRENT",
    "GRAPH_UNAVAILABLE",
    "GRAPH_REBUILDING",
    "CONTEXT_EXPIRED",
    "AGENT_LIMIT_REACHED",
}
COMPONENTS = {"api", "tool", "proposal", "projection", "rebuild", "runtime", "audit"}
OUTCOMES = {"success", "partial", "rejected", "failure", "unknown"}
UUID_FIELDS = {
    "request_id",
    "context_id",
    "update_request_id",
    "approval_id",
    "outbox_id",
    "rebuild_id",
    "graph_generation",
    "tool_call_id",
    "supersedes_update_request_id",
    "aggregate_id",
    "equipment_id",
    "maintenance_plan_id",
    "maintenance_record_id",
    "process_id",
    "production_operation_id",
    "product_id",
    "infrastructure_resource_id",
    "dependency_relation_id",
}
INTEGER_FIELDS = {"duration_ms", "attempt_count", "aggregate_version", "node_count", "event_count"}
ENUM_FIELDS = {
    "role": {"floor", "maintenance", "production", "manager"},
    "dependency": {"postgresql", "neo4j", "qdrant", "llm"},
    "http_method": {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "OTHER"},
    "aggregate_type": {"DependencyRelation", "ProductionOperationEquipmentAssignment"},
    "before_status": {
        "PREPARED",
        "WAITING_APPROVAL",
        "PENDING",
        "APPROVED",
        "COMPLETED",
        "CONSUMED",
        "REJECTED",
        "EXPIRED",
        "INVALIDATED",
        "FAILED",
    },
}
ENUM_FIELDS["after_status"] = ENUM_FIELDS["before_status"]
_CONTEXT = ContextVar("linescope_log_context", default=None)


def _string(value):
    return type(value) is str and len(value) <= 256


def _fields(values):
    result = {}
    for key, value in values.items():
        if key in UUID_FIELDS and type(value) in {str, UUID}:
            try:
                result[key] = str(UUID(str(value)))
            except ValueError:
                pass
        elif key in INTEGER_FIELDS and type(value) is int and value >= 0:
            result[key] = value
        elif key in ENUM_FIELDS and type(value) is str and value in ENUM_FIELDS[key]:
            result[key] = value
        elif key == "http_status" and type(value) is int and 100 <= value <= 599:
            result[key] = value
        elif key == "snapshot_hash" and _string(value) and re.fullmatch(r"[0-9a-f]{64}", value):
            result[key] = value
        elif key == "replayed" and type(value) is bool:
            result[key] = value
        elif key in {"actor_id", "route"} and _string(value):
            result[key] = value
        elif key == "tool" and type(value) is str:
            # Resolve lazily: the Tool registry also uses the logging boundary.
            from .reads import SCHEMAS
            from .tools import PREPARE_CATEGORIES

            if value in SCHEMAS or value in PREPARE_CATEGORIES:
                result[key] = value
    return result


@contextmanager
def request_context(request_id, **identity):
    """Use server/trusted IDs only; reset even on exceptions and cancellation."""
    token = _CONTEXT.set(_fields({"request_id": request_id, **identity}))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current_request_id():
    return (_CONTEXT.get() or {}).get("request_id")


def _diagnostic(error):
    # Never format the exception, its arguments, locals or source lines.
    name = type(error).__name__
    result = {"exception_type": name if _string(name) else "Exception"}
    frames = deque(maxlen=20)
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        module, function = frame.f_globals.get("__name__"), frame.f_code.co_name
        frames.append(
            {
                "module": module if _string(module) else "unknown",
                "function": function if _string(function) else "unknown",
                "line": traceback.tb_lineno,
            }
        )
        traceback = traceback.tb_next
    result["stack_frames"] = list(frames)
    return result


class JSONFormatter(logging.Formatter):
    def format(self, record):
        payload = getattr(record, "safe_event", None)
        if (
            type(payload) is not dict
            or payload.get("event") not in EVENTS
            or payload.get("component") not in COMPONENTS
            or payload.get("outcome") not in OUTCOMES
            or payload.get("result_code") not in CODES
        ):
            # Third-party messages/args/tracebacks can contain URLs or credentials.
            payload = {
                "component": "runtime",
                "event": "runtime.diagnostic",
                "outcome": "failure",
                "result_code": "RUNTIME_ERROR"
                if record.levelno >= logging.ERROR
                else "RUNTIME_WARNING",
                "request_id": current_request_id() or str(uuid4()),
            }
        payload = {
            **_fields(payload),
            "event": payload["event"],
            "component": payload["component"],
            "outcome": payload["outcome"],
            "result_code": payload["result_code"],
        }
        payload.setdefault("request_id", current_request_id() or str(uuid4()))
        error = getattr(record, "safe_error", None)
        if isinstance(error, BaseException):
            payload.update(_diagnostic(error))
        return json.dumps(
            {
                "log_schema_version": 1,
                "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
                "level": "ERROR"
                if record.levelno >= logging.ERROR
                else "WARNING"
                if record.levelno >= logging.WARNING
                else "INFO"
                if record.levelno >= logging.INFO
                else "DEBUG",
                "service": "linescope",
                **payload,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )


def _output_failed():
    try:
        sys.stderr.write("LineScope logging output failed\n")
    except Exception:
        pass


class SafeHandler(logging.StreamHandler):
    def flush(self):
        # logging.shutdown calls flush directly, outside emit/handleError.
        try:
            super().flush()
        except Exception:
            _output_failed()

    def handleError(self, record):
        # logging's default handleError prints record.msg, args and the traceback.
        _output_failed()


class EventLogger:
    def __init__(self, level="INFO", stream=None):
        if type(level) is not str or level not in LEVELS:
            raise ValueError("Invalid log level")
        # Each app owns its logger. Repeated app creation cannot duplicate handlers
        # or change another app's level/stream in the same process.
        self.logger = logging.Logger("linescope", LEVELS[level])
        self.logger.propagate = False
        self.handler = SafeHandler(sys.stdout if stream is None else stream)
        self.handler.setFormatter(JSONFormatter())
        self.logger.addHandler(self.handler)

    def emit(self, event, *, component, outcome, result_code, level="INFO", error=None, **fields):
        try:
            if (
                event not in EVENTS
                or component not in COMPONENTS
                or outcome not in OUTCOMES
                or result_code not in CODES
                or level not in LEVELS
            ):
                return
            if not self.logger.isEnabledFor(LEVELS[level]):
                return
            payload = {
                **_fields(fields),
                **(_CONTEXT.get() or {}),
                "event": event,
                "component": component,
                "outcome": outcome,
                "result_code": result_code,
            }
            payload.setdefault("request_id", str(uuid4()))
            self.logger.log(LEVELS[level], "", extra={"safe_event": payload, "safe_error": error})
        except Exception:
            _output_failed()


def configure_runtime_logging(events):
    """Called by the CLI only; no raw Uvicorn/access/SQL/provider messages."""
    root = logging.getLogger()
    handler = SafeHandler(events.handler.stream)
    handler.setFormatter(JSONFormatter())
    handler.setLevel(logging.WARNING)
    root.handlers = [handler]
    root.setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "httpx", "httpcore", "psycopg"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True
