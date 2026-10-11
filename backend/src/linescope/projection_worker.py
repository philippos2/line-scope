"""One normal-worker iteration on an already owned dedicated leadership session.

No daemon, reconnect, credentials, seed or Rebuild drain. Unknown/configuration
failures stop the caller; only known event defects become permanent failures.
"""

from dataclasses import dataclass
from time import monotonic
from uuid import UUID, uuid4

import psycopg
from neo4j.exceptions import DriverError, Neo4jError

from .logging import EventLogger, request_context
from .neo4j_projection import GraphGenerationUnavailable, Neo4jProjection, ProjectionIntegrityError
from .projection_application import ProjectionApplication
from .projection_payload import ProjectionPayloadError
from .projection_queue import ProjectionQueue
from .projection_state import ProjectionState

TRANSIENT_POSTGRES = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    psycopg.errors.LockNotAvailable,
    psycopg.errors.QueryCanceled,
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
)


@dataclass(frozen=True)
class ProjectionStep:
    status: str
    outbox_id: UUID | None = None


class ProjectionWorker:
    def __init__(self, database, adapter, *, logger=None, max_attempts=5, lease_seconds=30):
        self.logger = logger if logger is not None else EventLogger()
        self.queue = ProjectionQueue(
            database, max_attempts=max_attempts, lease_seconds=lease_seconds, logger=self.logger
        )
        if isinstance(adapter, Neo4jProjection) and adapter.timeout_seconds >= lease_seconds:
            raise ValueError("Neo4j timeout must be shorter than the Projection lease")
        self.application = ProjectionApplication(database, lease_seconds=lease_seconds)
        self.state = ProjectionState(database)
        self.adapter = adapter

    def run_once(self, leadership):
        """Recover eligible leases, then process at most one committed event."""
        with request_context(uuid4()):
            leadership.require()
            observation = self.state.observe()
            leadership.require()
            if observation.status in {"ERROR", "REBUILDING"}:
                return ProjectionStep("BLOCKED")
            self.queue.recover_expired(leadership)
            event = self.queue.claim(leadership)
            if event is None:
                blocked = self.state.observe().status in {"ERROR", "REBUILDING"}
                leadership.require()
                return ProjectionStep("BLOCKED" if blocked else "IDLE")
            started = monotonic()
            try:
                try:
                    applied = self.application.apply(leadership, event, self.adapter)
                except (ProjectionPayloadError, ProjectionIntegrityError):
                    return self._failed(leadership, event, started, permanent=True)
                except GraphGenerationUnavailable:
                    return self._failed(leadership, event, started, permanent=False)
                except TRANSIENT_POSTGRES:
                    return self._failed(leadership, event, started, permanent=False)
                except (Neo4jError, DriverError) as error:
                    if not error.is_retryable():
                        raise
                    return self._failed(leadership, event, started, permanent=False)
                status = "APPLIED" if applied else "FENCED"
                self._completed(event, started, status)
                return ProjectionStep(status, event["outbox_id"])
            except Exception as error:
                # Never manufacture DEAD for a programming/configuration error
                # or claim success when failure persistence/leadership is lost.
                self._completed(event, started, "UNKNOWN", error=error)
                raise

    def _failed(self, leadership, event, started, *, permanent):
        changed = self.queue.fail(leadership, event, permanent=permanent)
        if not changed:
            status = "FENCED"
        else:
            status = (
                "DEAD"
                if permanent or event["attempt_count"] >= self.queue.max_attempts
                else "RETRYABLE"
            )
            self.logger.emit(
                "projection.dead" if status == "DEAD" else "projection.retry_scheduled",
                component="projection",
                outcome="failure",
                result_code="INTERNAL_ERROR" if permanent else "DEPENDENCY_UNAVAILABLE",
                level="ERROR" if status == "DEAD" else "WARNING",
                **self._fields(event, started),
                after_status=status,
            )
        self._completed(event, started, status)
        return ProjectionStep(status, event["outbox_id"])

    @staticmethod
    def _fields(event, started):
        return {
            "outbox_id": event["outbox_id"],
            "update_request_id": event["update_request_id"],
            "aggregate_type": event["aggregate_type"],
            "aggregate_id": event["aggregate_id"],
            "aggregate_version": event["aggregate_version"],
            "attempt_count": event["attempt_count"],
            "duration_ms": max(0, int((monotonic() - started) * 1000)),
        }

    def _completed(self, event, started, status, *, error=None):
        self.logger.emit(
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
            **self._fields(event, started),
            **({"after_status": status} if status in {"APPLIED", "DEAD", "RETRYABLE"} else {}),
        )
