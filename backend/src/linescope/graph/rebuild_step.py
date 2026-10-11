"""One Rebuild drain iteration; the caller owns ticket, leader and lock."""

from dataclasses import dataclass
from time import monotonic
from uuid import UUID, uuid4

from ..logging import EventLogger, request_context
from .neo4j_projection import Neo4jProjection
from .projection_attempt import complete_projection_attempt
from .projection_errors import classify_projection_failure
from .rebuild_application import RebuildApplication
from .rebuild_queue import RebuildQueue


@dataclass(frozen=True)
class RebuildStepResult:
    status: str
    outbox_id: UUID | None = None


class RebuildStep:
    def __init__(self, database, adapter, *, logger=None, max_attempts=5, lease_seconds=30):
        if isinstance(adapter, Neo4jProjection) and adapter.timeout_seconds >= lease_seconds:
            raise ValueError("Neo4j timeout must be shorter than the Rebuild lease")
        self.logger = logger if logger is not None else EventLogger()
        self.queue = RebuildQueue(
            database, max_attempts=max_attempts, lease_seconds=lease_seconds, logger=self.logger
        )
        self.application = RebuildApplication(database, lease_seconds=lease_seconds)
        self.adapter = adapter

    def run_once(self, leadership, lock_connection, ticket):
        """Process at most one event; never wait, release locks or publish.

        DRAINED alone is completion. WAITING / RETRYABLE require bounded later
        iterations; DEAD / FENCED / unknown failures must stop the controller.
        Errors before claim do not manufacture an attempt completion log.
        """
        with request_context(uuid4()):
            claim = self.queue.claim(leadership, lock_connection, ticket)
            if claim.status != "CLAIMED":
                return RebuildStepResult(
                    claim.status, None if claim.event is None else claim.event["outbox_id"]
                )
            event, started = claim.event, monotonic()
            try:
                try:
                    applied = self.application.apply(
                        leadership, lock_connection, ticket, event, self.adapter
                    )
                except Exception as error:
                    permanent = classify_projection_failure(error)
                    if permanent is None:
                        raise
                    changed = self.queue.fail(
                        leadership, lock_connection, ticket, event, permanent=permanent
                    )
                    status = (
                        "FENCED"
                        if not changed
                        else "DEAD"
                        if permanent or event["attempt_count"] >= self.queue.max_attempts
                        else "RETRYABLE"
                    )
                else:
                    status = "APPLIED" if applied else "FENCED"
                self._completed(ticket, event, started, status)
                return RebuildStepResult(status, event["outbox_id"])
            except Exception as error:
                self._completed(ticket, event, started, "UNKNOWN", error=error)
                raise

    def _completed(self, ticket, event, started, status, *, error=None):
        complete_projection_attempt(
            self.logger,
            event,
            started,
            status,
            error=error,
            rebuild_id=ticket.rebuild_id,
            graph_generation=ticket.previous_generation,
        )
