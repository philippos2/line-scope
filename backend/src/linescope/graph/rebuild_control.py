"""Fenced Rebuild lifecycle primitives, not a complete controller or drain loop."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from ..persistence.core_rebuild import (
    begin_rebuild,
    fail_rebuild,
    heartbeat_rebuild,
    publish_rebuild,
)
from .graph_locks import require_exclusive_graph_mutation_lock
from .neo4j_generation import VerifiedGeneration


class RebuildControlRejected(RuntimeError):
    """Control ownership, drainage or publication preconditions do not hold."""


@dataclass(frozen=True)
class RebuildTicket:
    rebuild_id: UUID
    previous_generation: UUID | None


class RebuildControl:
    def __init__(self, database):
        self.database = database

    def begin(self, leadership):
        leadership.require()
        with self.database.transaction() as connection:
            rebuild_id = uuid4()
            previous = begin_rebuild(connection, rebuild_id)
            if previous is None:
                raise RebuildControlRejected("Rebuild control is absent or recovery is required")
            leadership.require()
        leadership.require()
        return RebuildTicket(rebuild_id, previous["active_generation"])

    def publish(self, leadership, lock_connection, ticket, verified, adapter):
        self._ticket(ticket)
        if not isinstance(verified, VerifiedGeneration):
            raise ValueError("A verified generation result is required")
        generation = UUID(verified.generation)
        if generation == ticket.previous_generation:
            raise RebuildControlRejected("Rebuild must publish a new generation")
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        # A caller DTO alone is not evidence that Neo4j committed validation.
        adapter.require_verified(
            generation=generation,
            snapshot_hash=verified.snapshot_hash,
            leadership=leadership,
        )
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        with self.database.transaction() as connection:
            if not publish_rebuild(connection, ticket, generation):
                raise RebuildControlRejected("Rebuild is stale or Outbox is not drained")
            require_exclusive_graph_mutation_lock(lock_connection)
            leadership.require()
        leadership.require()

    def fail(self, leadership, ticket):
        self._ticket(ticket)
        leadership.require()
        with self.database.transaction() as connection:
            changed = fail_rebuild(connection, ticket)
            leadership.require()
        leadership.require()
        return changed

    def heartbeat(self, leadership, lock_connection, ticket):
        self._ticket(ticket)
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        with self.database.transaction() as connection:
            if not heartbeat_rebuild(connection, ticket):
                raise RebuildControlRejected("Rebuild heartbeat ownership is stale")
            require_exclusive_graph_mutation_lock(lock_connection)
            leadership.require()
        leadership.require()

    @staticmethod
    def _ticket(ticket):
        if (
            not isinstance(ticket, RebuildTicket)
            or not isinstance(ticket.rebuild_id, UUID)
            or (
                ticket.previous_generation is not None
                and not isinstance(ticket.previous_generation, UUID)
            )
        ):
            raise ValueError("An internal Rebuild ticket is required")
