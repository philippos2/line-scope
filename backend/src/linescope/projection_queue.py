"""Internal claim and failure recovery stages; not a running Projection worker or Graph adapter."""

from .core_outbox import claim_graph_event, fail_graph_event, recover_expired_graph_events
from .graph_locks import require_read_committed_transaction


class ProjectionQueue:
    def __init__(self, database, *, max_attempts=5, lease_seconds=30):
        if any(type(value) is not int or value <= 0 for value in (max_attempts, lease_seconds)):
            raise ValueError("Projection attempt/lease limits must be positive integers")
        self.database = database
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds

    def claim(self, leadership):
        """Commit PROCESSING before any later mutation lock or Neo4j work.

        Caller retains the dedicated session leader. Lost leadership stops the
        operation; a committed claim is later recoverable by the lease protocol.
        No HTTP/Tool, Graph apply or APPLIED acknowledgement yet.
        """
        leadership.require()
        with self.database.transaction() as connection:
            require_read_committed_transaction(connection)
            event = claim_graph_event(connection, self.max_attempts)
            leadership.require()
        leadership.require()
        return event if event is not None and event["status"] == "PROCESSING" else None

    def fail(self, leadership, event, *, permanent=False):
        """Retire only this exact attempt; never persist an exception or payload.

        A stale/duplicate report returns False. Attempt count increments only
        on claim. A permanent failure or the last allowed attempt becomes DEAD.
        """
        attempt = event["attempt_count"]
        if type(permanent) is not bool or type(attempt) is not int or attempt < 1:
            raise ValueError("Invalid Projection failure metadata")
        dead = permanent or attempt >= self.max_attempts
        code = (
            "PROJECTION_PERMANENT_FAILURE"
            if permanent
            else "PROJECTION_ATTEMPTS_EXHAUSTED"
            if dead
            else "PROJECTION_TRANSIENT_FAILURE"
        )
        delay = min(2 ** min(attempt - 1, 6), 60)
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
        leadership.require()
        with self.database.transaction() as connection:
            require_read_committed_transaction(connection)
            recovered = recover_expired_graph_events(connection, self.lease_seconds)
            leadership.require()
        leadership.require()
        return recovered
