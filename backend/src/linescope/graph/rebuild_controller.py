"""Rebuild/Restore and abandoned-flag recovery on an owned leader session.

No worker daemon, repair of missing Graph behind a non-NULL pointer or CLI.
Failure never deletes old generations or assumes a cross-store rollback.
"""

from time import monotonic, sleep
from uuid import uuid4

from ..logging import EventLogger, request_context
from .graph_locks import acquire_graph_mutation_lock
from .postgres_timeout import cap_postgres_transaction
from .projection_state import ProjectionState
from .rebuild_control import RebuildControl
from .rebuild_drain import DeadlineLeadership, RebuildDrain
from .rebuild_snapshot import read_rebuild_snapshot
from .rebuild_step import RebuildStep


class _HeartbeatStep:
    def __init__(self, control, step):
        self.control, self.step = control, step

    def run_once(self, leadership, lock_connection, ticket):
        self.control.heartbeat(leadership, lock_connection, ticket)
        return self.step.run_once(leadership, lock_connection, ticket)


class RebuildController:
    def __init__(
        self,
        database,
        projection,
        generation,
        *,
        timeout_ms=60000,
        logger=None,
        clock=monotonic,
        wait=sleep,
    ):
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("Rebuild timeout must be a positive integer")
        self.database, self.generation = database, generation
        self.timeout_ms, self.clock = timeout_ms, clock
        self.logger = logger if logger is not None else EventLogger()
        self.control = RebuildControl(database)
        step = RebuildStep(database, projection, logger=self.logger)
        self.drain = RebuildDrain(_HeartbeatStep(self.control, step), clock=clock, wait=wait)

    def run(self, leadership):
        """Start a new Rebuild; remaining ownership requires explicit recovery."""
        return self._run(leadership, recovery=False)

    def recover(self, leadership):
        """Adopt a remaining flag only after PG and actual Graph verification."""
        return self._run(leadership, recovery=True)

    def _started(self, ticket):
        self.logger.emit(
            "rebuild.started",
            component="rebuild",
            outcome="success",
            result_code="OK",
            rebuild_id=ticket.rebuild_id,
            graph_generation=ticket.previous_generation,
        )

    def _snapshot(self, lock_connection, leadership):
        cap_postgres_transaction(lock_connection, leadership)
        return read_rebuild_snapshot(lock_connection)

    def _run(self, leadership, *, recovery):
        """Build a fresh generation, then publish only verified, drained state.

        Leader is acquired by caller before this method. The controller owns
        the mutation transaction and releases it on every exit. Cleanup uses
        the original leader after timeout; lost leadership leaves recovery to
        the next controller. A failed post-commit check is an unknown outcome.
        """
        started = self.clock()
        guard = DeadlineLeadership(leadership, started + self.timeout_ms / 1000, self.clock)
        ticket = None
        observed_ticket = None
        candidate = None
        with request_context(uuid4()):
            try:
                if not recovery:
                    ticket = self.control.begin(guard)
                    self._started(ticket)
                with self.database.transaction() as lock:
                    guard.require()
                    cap_postgres_transaction(lock, guard)
                    acquire_graph_mutation_lock(lock, shared=False)
                    guard.require()
                    if recovery:
                        observed = self.control.observe(guard, lock)
                        observed_ticket = observed.recovery_ticket()
                        old = observed_ticket
                        proof = None
                        if old.previous_generation is not None:
                            proof = self.generation.observe_validation(
                                generation=old.previous_generation, leadership=guard
                            )
                        guard.require()
                        # Assign only the newly confirmed owner. A pre-adoption
                        # failure must never clear or fail the abandoned ticket.
                        ticket = self.control.resume(
                            guard,
                            lock,
                            old,
                            verified=proof,
                            adapter=self.generation if proof is not None else None,
                        )
                        self._started(ticket)
                    if ticket.previous_generation is None:
                        observation = ProjectionState(self.database).observe(lock)
                        guard.require()
                        # DEAD follows the normal drain stop path without
                        # constructing or installing a work generation.
                        if not observation.counts["DEAD"] and any(
                            observation.counts[state]
                            for state in ("PENDING", "PROCESSING", "RETRYABLE")
                        ):
                            self.control.heartbeat(guard, lock, ticket)
                            snapshot = self._snapshot(lock, guard)
                            guard.require()
                            candidate = uuid4()
                            work = self.generation.build(
                                generation=candidate, snapshot=snapshot, leadership=guard
                            )
                            guard.require()
                            # Staging commits a new fence; subsequent drain,
                            # failure and publication must use that ticket.
                            ticket = self.control.stage_restore(
                                guard, lock, ticket, work, self.generation
                            )
                    drained = self.drain.run(guard, lock, ticket, deadline=guard.deadline)
                    self.control.heartbeat(guard, lock, ticket)
                    snapshot = self._snapshot(lock, guard)
                    guard.require()
                    candidate = uuid4()
                    verified = self.generation.build(
                        generation=candidate, snapshot=snapshot, leadership=guard
                    )
                    guard.require()
                    self.control.publish(guard, lock, ticket, verified, self.generation)
                guard.require()
                self.logger.emit(
                    "rebuild.completed",
                    component="rebuild",
                    outcome="success",
                    result_code="OK",
                    rebuild_id=ticket.rebuild_id,
                    graph_generation=verified.generation,
                    node_count=verified.node_count,
                    event_count=drained.applied_count,
                    duration_ms=max(0, int((self.clock() - started) * 1000)),
                )
                return verified
            except Exception as error:
                failed = False
                diagnostic = error
                if ticket is not None:
                    try:
                        failed = self.control.fail(leadership, ticket)
                    except Exception as cleanup_error:
                        # Keep the original failure; do not reconnect or claim
                        # that failure state persisted without confirmation.
                        diagnostic = cleanup_error
                diagnostic_ticket = ticket if ticket is not None else observed_ticket
                self.logger.emit(
                    "rebuild.failed",
                    component="rebuild",
                    outcome="failure" if failed else "unknown",
                    result_code="INTERNAL_ERROR",
                    level="ERROR",
                    error=diagnostic,
                    rebuild_id=None if diagnostic_ticket is None else diagnostic_ticket.rebuild_id,
                    graph_generation=candidate
                    if candidate is not None
                    else None
                    if diagnostic_ticket is None
                    else diagnostic_ticket.previous_generation,
                    duration_ms=max(0, int((self.clock() - started) * 1000)),
                )
                raise
