"""Internal claim stage only; not a running Projection worker or Graph adapter."""

from .core_outbox import claim_graph_event
from .graph_locks import require_read_committed_transaction


class ProjectionQueue:
    def __init__(self, database):
        self.database = database

    def claim(self, leadership):
        """Commit PROCESSING before any later mutation lock or Neo4j work.

        Caller retains the dedicated session leader. Lost leadership stops the
        operation; a committed claim is later recoverable by the lease protocol.
        No HTTP/Tool, Graph apply, APPLIED acknowledgement or lease recovery yet.
        """
        leadership.require()
        with self.database.transaction() as connection:
            require_read_committed_transaction(connection)
            event = claim_graph_event(connection)
            leadership.require()
        leadership.require()
        return event
