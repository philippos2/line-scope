"""Fenced Rebuild lifecycle primitives, not a complete controller or drain loop."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from ..persistence.core_rebuild import (
    begin_rebuild,
    fail_rebuild,
    heartbeat_rebuild,
    publish_rebuild,
    resume_rebuild,
    stage_restore_generation,
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

    def stage_restore(self, leadership, lock_connection, ticket, verified, adapter):
        """Return a new fence after installing a verified Restore drain target.

        This is not publication: flag and fatal error remain, Outbox is untouched.
        Caller must replace its ticket before drain/failure/final publication.
        Only an absent PG pointer is handled; missing Neo4j data behind an
        existing pointer requires a separate recovery decision.
        """
        self._ticket(ticket)
        if ticket.previous_generation is not None:
            raise RebuildControlRejected("Restore staging requires an absent generation pointer")
        if not isinstance(verified, VerifiedGeneration):
            raise ValueError("A verified generation result is required")
        generation = UUID(verified.generation)
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        adapter.require_verified(
            generation=generation,
            snapshot_hash=verified.snapshot_hash,
            leadership=leadership,
        )
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        with self.database.transaction() as connection:
            if not stage_restore_generation(connection, ticket, generation):
                raise RebuildControlRejected("Restore is stale, DEAD or has no undrained events")
            require_exclusive_graph_mutation_lock(lock_connection)
            leadership.require()
        # Match begin/publish: post-commit loss remains unknown, never undo it.
        leadership.require()
        return RebuildTicket(ticket.rebuild_id, generation)

    def resume(self, leadership, lock_connection, ticket, *, verified=None, adapter=None):
        """Adopt a remaining flag; never infer completed publication or clear it.

        Caller has acquired leadership and the exclusive mutation lock, and
        supplies the observed old ticket. A non-NULL pointer requires actual
        committed Neo4j validation, not just a caller-provided DTO. Recovery
        orchestration, absent Graph repair and generation cleanup remain separate.
        """
        self._ticket(ticket)
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        if ticket.previous_generation is not None:
            if (
                not isinstance(verified, VerifiedGeneration)
                or UUID(verified.generation) != ticket.previous_generation
                or adapter is None
            ):
                raise RebuildControlRejected("Recovery requires proof of the existing generation")
            adapter.require_verified(
                generation=ticket.previous_generation,
                snapshot_hash=verified.snapshot_hash,
                leadership=leadership,
            )
        elif verified is not None or adapter is not None:
            raise RebuildControlRejected("Recovery proof must match the existing pointer")
        leadership.require()
        require_exclusive_graph_mutation_lock(lock_connection)
        rebuild_id = uuid4()
        with self.database.transaction() as connection:
            if not resume_rebuild(connection, ticket, rebuild_id):
                raise RebuildControlRejected("Recovery ownership or publication state changed")
            require_exclusive_graph_mutation_lock(lock_connection)
            leadership.require()
        leadership.require()
        return RebuildTicket(rebuild_id, ticket.previous_generation)

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
