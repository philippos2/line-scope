"""One fenced Rebuild drain claim/recovery step, without external Projection.

The controller owns leader and exclusive mutation locks for the entire drain.
Short PG transactions retain normal attempt/backoff/lease semantics.
"""

from dataclasses import dataclass
from time import monotonic

from ..persistence.core_outbox import (
    claim_rebuild_graph_event,
    fail_rebuild_graph_event,
    read_rebuild_queue_state,
    recover_expired_rebuild_graph_events,
)
from .graph_locks import require_exclusive_graph_mutation_lock, require_read_committed_transaction
from .neo4j_projection import GraphGenerationUnavailable
from .postgres_timeout import postgres_budget_transaction
from .projection_failure import projection_failure
from .rebuild_control import RebuildControlRejected, RebuildTicket


@dataclass(frozen=True)
class RebuildClaim:
    status: str
    event: dict | None = None


class RebuildQueue:
    def __init__(self, database, *, max_attempts=5, lease_seconds=30, logger=None):
        if any(type(value) is not int or value <= 0 for value in (max_attempts, lease_seconds)):
            raise ValueError("Rebuild attempt/lease limits must be positive integers")
        self.database, self.max_attempts, self.lease_seconds = database, max_attempts, lease_seconds
        self.logger = logger

    def claim(self, leadership, lock_connection, ticket):
        started = monotonic()
        recovered = []
        if not isinstance(ticket, RebuildTicket):
            raise ValueError("An internal Rebuild ticket is required")
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        with postgres_budget_transaction(self.database, leadership) as connection:
            require_read_committed_transaction(connection)
            state = read_rebuild_queue_state(connection, ticket)
            if state is None:
                raise RebuildControlRejected("Rebuild drain ownership is stale")
            if state["dead"]:
                result = RebuildClaim("DEAD")
            elif state["undrained"] == 0:
                result = RebuildClaim("DRAINED")
            else:
                if state["active_generation"] is None:
                    raise GraphGenerationUnavailable("Rebuild drain target generation is absent")
                recovered = recover_expired_rebuild_graph_events(
                    connection, ticket, self.lease_seconds
                )
                event = claim_rebuild_graph_event(connection, ticket, self.max_attempts)
                result = (
                    RebuildClaim("WAITING")
                    if event is None
                    else RebuildClaim("DEAD", event)
                    if event["status"] == "DEAD"
                    else RebuildClaim("CLAIMED", event)
                )
            leadership.require()
        leadership.require()
        for event in recovered:
            # Recovery and claim share one transaction: a reclaimed candidate
            # never commits RETRYABLE, so do not log that intermediate state.
            if result.event is None or event["outbox_id"] != result.event["outbox_id"]:
                self._transition(ticket, event, started, "RETRYABLE", code="RESOURCE_BUSY")
        if result.status == "DEAD" and result.event is not None:
            self._transition(ticket, result.event, started, "DEAD", code="INTERNAL_ERROR")
        return result

    def fail(self, leadership, lock_connection, ticket, event, *, permanent=False):
        """Retire only the exact saved attempt owned by this Rebuild.

        Caller classifies known failures; never accept exception text as a DB
        value. Unknown failures must propagate instead of manufacturing DEAD.
        Lease expiry alone does not change attempt identity; reclaims do.
        """
        if not isinstance(ticket, RebuildTicket):
            raise ValueError("An internal Rebuild ticket is required")
        dead, code, delay = projection_failure(
            event["attempt_count"], self.max_attempts, permanent=permanent
        )
        started = monotonic()
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        with postgres_budget_transaction(self.database, leadership) as connection:
            require_read_committed_transaction(connection)
            changed = fail_rebuild_graph_event(
                connection, event, ticket, dead=dead, delay_seconds=delay, error_code=code
            )
            require_exclusive_graph_mutation_lock(lock_connection)
            leadership.require()
        leadership.require()
        if changed:
            self._transition(
                ticket,
                event,
                started,
                "DEAD" if dead else "RETRYABLE",
                code="INTERNAL_ERROR" if permanent else "DEPENDENCY_UNAVAILABLE",
            )
        return changed

    def _transition(self, ticket, event, started, status, *, code):
        if self.logger is None:
            return
        self.logger.emit(
            "projection.dead" if status == "DEAD" else "projection.retry_scheduled",
            component="projection",
            outcome="failure",
            result_code=code,
            level="ERROR" if status == "DEAD" else "WARNING",
            rebuild_id=ticket.rebuild_id,
            graph_generation=ticket.previous_generation,
            **{
                key: event[key]
                for key in (
                    "outbox_id",
                    "update_request_id",
                    "aggregate_type",
                    "aggregate_id",
                    "aggregate_version",
                    "attempt_count",
                )
            },
            duration_ms=max(0, int((monotonic() - started) * 1000)),
            before_status="PROCESSING" if status == "RETRYABLE" else None,
            after_status=status,
        )
