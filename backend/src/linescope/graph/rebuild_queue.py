"""One fenced Rebuild drain claim/recovery step, without external Projection.

The controller owns leader and exclusive mutation locks for the entire drain.
Short PG transactions retain normal attempt/backoff/lease semantics.
"""

from dataclasses import dataclass

from ..persistence.core_outbox import (
    claim_rebuild_graph_event,
    read_rebuild_queue_state,
    recover_expired_rebuild_graph_events,
)
from .graph_locks import require_exclusive_graph_mutation_lock
from .neo4j_projection import GraphGenerationUnavailable
from .rebuild_control import RebuildControlRejected, RebuildTicket


@dataclass(frozen=True)
class RebuildClaim:
    status: str
    event: dict | None = None


class RebuildQueue:
    def __init__(self, database, *, max_attempts=5, lease_seconds=30):
        if any(type(value) is not int or value <= 0 for value in (max_attempts, lease_seconds)):
            raise ValueError("Rebuild attempt/lease limits must be positive integers")
        self.database, self.max_attempts, self.lease_seconds = database, max_attempts, lease_seconds

    def claim(self, leadership, lock_connection, ticket):
        if not isinstance(ticket, RebuildTicket):
            raise ValueError("An internal Rebuild ticket is required")
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        with self.database.transaction() as connection:
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
                recover_expired_rebuild_graph_events(connection, ticket, self.lease_seconds)
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
        return result
