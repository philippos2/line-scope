"""Apply one saved Rebuild attempt under the controller's existing lock."""

from functools import partial

from ..persistence.core_outbox import (
    acknowledge_rebuild_graph_application,
    read_rebuild_graph_application,
)
from .graph_locks import require_exclusive_graph_mutation_lock
from .neo4j_projection import Neo4jProjection
from .projection_application import apply_locked_graph_attempt
from .rebuild_control import RebuildTicket


class RebuildApplication:
    def __init__(self, database, *, lease_seconds=30):
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("Rebuild lease must be a positive integer")
        self.database, self.lease_seconds = database, lease_seconds

    def apply(self, leadership, lock_connection, ticket, event, adapter):
        """True only after adapter commit and a fenced, committed APPLIED record.

        Never reacquire or release the caller's lock, or retry external I/O.
        Existing fatal_error is recoverable; ticket, lease, DEAD and generation
        fences remain mandatory before I/O and at acknowledgement.
        """
        if not isinstance(ticket, RebuildTicket):
            raise ValueError("An internal Rebuild ticket is required")
        if isinstance(adapter, Neo4jProjection) and adapter.timeout_seconds >= self.lease_seconds:
            raise ValueError("Neo4j timeout must be shorter than the Rebuild lease")
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        return apply_locked_graph_attempt(
            self.database,
            leadership,
            lock_connection,
            event,
            adapter,
            self.lease_seconds,
            partial(read_rebuild_graph_application, ticket=ticket),
            partial(acknowledge_rebuild_graph_application, ticket=ticket),
            require_exclusive_graph_mutation_lock,
        )
