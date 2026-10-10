"""Normal-worker application fence; the real Neo4j adapter is still separate.

The adapter must return only after its atomic Neo4j commit, including marker
verification for same/older versions. It must check the supplied leadership
before further Graph work. This service never treats an adapter failure as
APPLIED, never retries an external commit itself, and is not a Rebuild drain.
"""

from .core_outbox import acknowledge_graph_application, read_graph_application
from .graph_locks import acquire_graph_mutation_lock, require_read_committed_transaction
from .projection_payload import validate_projection_payload


class ProjectionApplication:
    def __init__(self, database, *, lease_seconds=30):
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("Projection lease must be a positive integer")
        self.database = database
        self.lease_seconds = lease_seconds

    def apply(self, leadership, event, adapter):
        """Return False if fenced; True only after a committed APPLIED record.

        Leadership precedes the exclusive mutation lock. Hold that lock across
        adapter commit and the separate short acknowledgement transaction.
        PostgreSQL never holds an event/control row lock during external I/O.
        Exceptions propagate to the worker's failure/recovery boundary.
        """
        leadership.require()
        with self.database.transaction() as lock_connection:
            acquire_graph_mutation_lock(lock_connection, shared=False)
            leadership.require()
            with self.database.transaction() as connection:
                require_read_committed_transaction(connection)
                saved = read_graph_application(connection, event, self.lease_seconds)
            if saved is None:
                return False
            payload = validate_projection_payload(saved["payload"])
            if (
                payload["aggregate_type"] != saved["aggregate_type"]
                or payload["aggregate_id"] != str(saved["aggregate_id"])
                or payload["aggregate_version"] != saved["aggregate_version"]
            ):
                raise ValueError("Projection payload disagrees with saved aggregate")
            leadership.require()
            adapter.apply(
                generation=saved["active_generation"],
                outbox_id=saved["outbox_id"],
                payload=payload,
                leadership=leadership,
            )
            leadership.require()
            require_read_committed_transaction(lock_connection)
            with self.database.transaction() as connection:
                require_read_committed_transaction(connection)
                changed = acknowledge_graph_application(
                    connection, event, self.lease_seconds, saved["active_generation"]
                )
                leadership.require()
            leadership.require()
            return changed
