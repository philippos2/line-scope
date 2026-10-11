"""Shared, allowlisted attempt completion logs for worker and Rebuild."""

from time import monotonic


def projection_attempt_fields(event, started):
    return {
        "outbox_id": event["outbox_id"],
        "update_request_id": event["update_request_id"],
        "aggregate_type": event["aggregate_type"],
        "aggregate_id": event["aggregate_id"],
        "aggregate_version": event["aggregate_version"],
        "attempt_count": event["attempt_count"],
        "duration_ms": max(0, int((monotonic() - started) * 1000)),
    }


def complete_projection_attempt(logger, event, started, status, *, error=None, **identity):
    logger.emit(
        "projection.attempt.completed",
        component="projection",
        outcome="success"
        if status == "APPLIED"
        else "unknown"
        if status in {"FENCED", "UNKNOWN"}
        else "failure",
        result_code="OK"
        if status == "APPLIED"
        else "GRAPH_NOT_CURRENT"
        if status == "FENCED"
        else "INTERNAL_ERROR"
        if status in {"DEAD", "UNKNOWN"}
        else "DEPENDENCY_UNAVAILABLE",
        level="INFO"
        if status == "APPLIED"
        else "ERROR"
        if status in {"DEAD", "UNKNOWN"}
        else "WARNING",
        error=error,
        **projection_attempt_fields(event, started),
        **identity,
        **({"after_status": status} if status in {"APPLIED", "DEAD", "RETRYABLE"} else {}),
    )
