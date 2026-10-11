"""Deadline-bounded drain on caller-owned leadership and mutation lock.

No publication, lifecycle flag changes, reconnect or background thread. The
caller supplies the absolute monotonic deadline shared with other Rebuild phases.
"""

from dataclasses import dataclass
from math import isfinite
from time import monotonic, sleep

from .graph_locks import require_exclusive_graph_mutation_lock


class RebuildDrainTimeout(TimeoutError):
    """The Rebuild budget expired; no successful drain result may be used."""


class RebuildDrainStopped(RuntimeError):
    def __init__(self, result):
        super().__init__("Rebuild drain cannot continue")
        self.status, self.outbox_id = result.status, result.outbox_id


@dataclass(frozen=True)
class RebuildDrainResult:
    applied_count: int


class DeadlineLeadership:
    """Add deadline checks to existing adapter/queue leadership checkpoints."""

    def __init__(self, leadership, deadline, clock):
        self.leadership, self.deadline, self.clock = leadership, deadline, clock

    def remaining(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise RebuildDrainTimeout("Rebuild drain deadline expired")
        return remaining

    def require(self):
        self.remaining()
        self.leadership.require()
        self.remaining()


class RebuildDrain:
    def __init__(self, step, *, poll_seconds=1, clock=monotonic, wait=sleep):
        if (
            type(poll_seconds) not in (int, float)
            or not isfinite(poll_seconds)
            or poll_seconds <= 0
        ):
            raise ValueError("Rebuild poll interval must be positive and finite")
        self.step, self.poll_seconds, self.clock, self.wait = step, poll_seconds, clock, wait

    def run(self, leadership, lock_connection, ticket, *, deadline):
        """Return only after DRAINED before deadline; retain caller-owned locks.

        DEAD / FENCED stop immediately. Only WAITING / RETRYABLE wait; unknown
        exceptions propagate. Blocking I/O remains bounded by driver/DB timeouts;
        expiry is checked at their existing leadership checkpoints, not by an
        unsafe thread cancellation or releasing locks around ongoing Graph I/O.
        """
        if type(deadline) not in (int, float) or not isfinite(deadline):
            raise ValueError("An absolute finite monotonic deadline is required")
        guard = DeadlineLeadership(leadership, deadline, self.clock)
        applied_count = 0
        while True:
            guard.require()
            require_exclusive_graph_mutation_lock(lock_connection)
            guard.require()
            result = self.step.run_once(guard, lock_connection, ticket)
            guard.require()
            require_exclusive_graph_mutation_lock(lock_connection)
            guard.require()
            if result.status == "DRAINED":
                return RebuildDrainResult(applied_count)
            if result.status == "APPLIED":
                applied_count += 1
            elif result.status in {"WAITING", "RETRYABLE"}:
                self.wait(min(self.poll_seconds, guard.remaining()))
            elif result.status in {"DEAD", "FENCED"}:
                raise RebuildDrainStopped(result)
            else:
                raise RuntimeError("Unexpected Rebuild step status")
