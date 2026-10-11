"""Internal claim and failure recovery stages; not a running Projection worker or Graph adapter."""

from time import monotonic

from ..persistence.core_outbox import (
    claim_graph_event,
    fail_graph_event,
    recover_expired_graph_events,
)
from .graph_locks import require_read_committed_transaction
from .projection_failure import projection_failure


class ProjectionQueue:
    def __init__(self, database, *, max_attempts=5, lease_seconds=30, logger=None):
        if any(type(value) is not int or value <= 0 for value in (max_attempts, lease_seconds)):
            raise ValueError("Projection attempt/lease limits must be positive integers")
        self.database = database
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.logger = logger

    def claim(self, leadership):
        """Commit PROCESSING before any later mutation lock or Neo4j work.

        Caller retains the dedicated session leader. Lost leadership stops the
        operation; a committed claim is later recoverable by the lease protocol.
        No HTTP/Tool, Graph apply or APPLIED acknowledgement yet.
        """
        started = monotonic()
        leadership.require()
        with self.database.transaction() as connection:
            require_read_committed_transaction(connection)
            event = claim_graph_event(connection, self.max_attempts)
            leadership.require()
        leadership.require()
        if event is not None and event["status"] == "DEAD" and self.logger is not None:
            self.logger.emit(
                "projection.dead",
                component="projection",
                outcome="failure",
                result_code="INTERNAL_ERROR",
                level="ERROR",
                outbox_id=event["outbox_id"],
                update_request_id=event["update_request_id"],
                aggregate_type=event["aggregate_type"],
                aggregate_id=event["aggregate_id"],
                aggregate_version=event["aggregate_version"],
                attempt_count=event["attempt_count"],
                duration_ms=max(0, int((monotonic() - started) * 1000)),
                after_status="DEAD",
            )
        return event if event is not None and event["status"] == "PROCESSING" else None

    def fail(self, leadership, event, *, permanent=False):
        """Retire only this exact attempt; never persist an exception or payload.

        A stale/duplicate report returns False. Attempt count increments only
        on claim. A permanent failure or the last allowed attempt becomes DEAD.
        """
        dead, code, delay = projection_failure(
            event["attempt_count"], self.max_attempts, permanent=permanent
        )
        leadership.require()
        with self.database.transaction() as connection:
            require_read_committed_transaction(connection)
            changed = fail_graph_event(
                connection, event, dead=dead, delay_seconds=delay, error_code=code
            )
            leadership.require()
        leadership.require()
        return changed

    def recover_expired(self, leadership):
        """After leadership acquisition, return expired PROCESSING to RETRYABLE.

        Rebuild's flag fences its heartbeat/drain from this normal recovery.
        Max-attempt events are retired as DEAD at the next claim, not retried.
        """
        started = monotonic()
        leadership.require()
        with self.database.transaction() as connection:
            require_read_committed_transaction(connection)
            recovered = recover_expired_graph_events(connection, self.lease_seconds)
            leadership.require()
        leadership.require()
        if self.logger is not None:
            for event in recovered:
                self.logger.emit(
                    "projection.retry_scheduled",
                    component="projection",
                    outcome="failure",
                    result_code="RESOURCE_BUSY",
                    level="WARNING",
                    **event,
                    duration_ms=max(0, int((monotonic() - started) * 1000)),
                    before_status="PROCESSING",
                    after_status="RETRYABLE",
                )
        return [event["outbox_id"] for event in recovered]
