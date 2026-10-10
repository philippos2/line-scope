"""Real PostgreSQL shared/exclusive coordination, with caller-owned transactions."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from linescope.database import MIGRATION_LOCK, Database
from linescope.graph_locks import GRAPH_MUTATION_LOCK, acquire_graph_mutation_lock
from linescope.projection_state import ProjectionState


@pytest.fixture
def store(db):
    db.migrate()
    return db


def short_wait(db):
    return Database(replace(db.settings, lock_ms=100, statement_ms=1000))


@pytest.mark.parametrize(
    "first_shared,second_shared", [(True, True), (True, False), (False, True), (False, False)]
)
def test_shared_readers_coexist_and_exclusive_conflicts(store, first_shared, second_shared):
    with store.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=first_shared)
        if first_shared and second_shared:
            with short_wait(store).transaction() as other:
                acquire_graph_mutation_lock(other, shared=second_shared)
        else:
            with (
                pytest.raises(psycopg.errors.LockNotAvailable),
                short_wait(store).transaction() as other,
            ):
                acquire_graph_mutation_lock(other, shared=second_shared)


@pytest.mark.parametrize("shared", [True, False])
@pytest.mark.parametrize("rollback", [True, False])
def test_transaction_end_releases_lock_even_on_rollback(store, shared, rollback):
    with store.connect() as holder:
        if rollback:
            with pytest.raises(RuntimeError), holder.transaction():
                acquire_graph_mutation_lock(holder, shared=shared)
                raise RuntimeError("abort")
        else:
            with holder.transaction():
                acquire_graph_mutation_lock(holder, shared=shared)
        assert holder.info.transaction_status == TransactionStatus.IDLE
        # The original session remains open: this proves transaction ownership.
        with short_wait(store).transaction() as other:
            acquire_graph_mutation_lock(other, shared=False)


@pytest.mark.parametrize("shared", [True, False])
def test_autocommit_connection_is_rejected_before_lock_acquisition(store, shared):
    with store.connect() as c:
        with pytest.raises(ValueError, match="active PostgreSQL transaction"):
            acquire_graph_mutation_lock(c, shared=shared)
        assert c.info.transaction_status == TransactionStatus.IDLE


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_stale_transaction_snapshots_are_rejected(store, isolation):
    with store.transaction() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        with pytest.raises(ValueError, match="READ COMMITTED"):
            acquire_graph_mutation_lock(c, shared=True)
        with pytest.raises(ValueError, match="READ COMMITTED"):
            ProjectionState(store).observe(c)


@pytest.mark.parametrize("value", [None, 0, 1, "shared"])
def test_mode_must_be_explicit_server_boolean(value):
    with pytest.raises(ValueError, match="server boolean"):
        acquire_graph_mutation_lock(None, shared=value)


def test_graph_key_does_not_conflict_with_migration_lock(store):
    assert GRAPH_MUTATION_LOCK != MIGRATION_LOCK
    with store.transaction() as c:
        c.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        with short_wait(store).transaction() as other:
            acquire_graph_mutation_lock(other, shared=False)


def test_observation_uses_the_locked_connection_without_opening_another(store):
    class NoConnections:
        def transaction(self):
            raise AssertionError("Must use the caller connection")

    gate = ProjectionState(NoConnections())
    with store.transaction() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
        acquire_graph_mutation_lock(c, shared=True)
        observed = gate.observe(c)
        assert observed.status == "ERROR"
        # Observation does not commit/release the caller lock.
        with (
            pytest.raises(psycopg.errors.LockNotAvailable),
            short_wait(store).transaction() as other,
        ):
            acquire_graph_mutation_lock(other, shared=False)
        assert c.info.transaction_status == TransactionStatus.INTRANS


def test_read_after_wait_observes_latest_committed_generation(store):
    started = Event()
    generation = uuid4()

    def reader():
        with store.transaction() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
            started.set()
            acquire_graph_mutation_lock(c, shared=True)
            return ProjectionState(store).observe(c)

    with ThreadPoolExecutor(1) as pool:
        # Release the lock before executor shutdown, including assertion failures.
        with store.transaction() as c:
            acquire_graph_mutation_lock(c, shared=False)
            c.execute(
                "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
                (generation,),
            )
            pending = pool.submit(reader)
            assert started.wait(5)
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.15)
        observed = pending.result(timeout=5)
    assert observed.status == "CURRENT" and observed.active_generation == generation


def test_same_transaction_recheck_sees_control_change_during_analysis(store):
    with store.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL", (uuid4(),)
        )
    with store.transaction() as reader:
        c = reader
        c.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
        acquire_graph_mutation_lock(c, shared=True)
        gate = ProjectionState(store)
        assert gate.observe(c).status == "CURRENT"
        # A fatal error can be recorded independently; the end check must see it.
        with store.transaction() as writer:
            writer.execute("UPDATE graph_projection_control SET fatal_error='PROJECTION_FAILED'")
        assert gate.observe(c).status == "ERROR"


def test_observation_does_not_commit_caller_business_changes(store):
    with pytest.raises(RuntimeError), store.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL", (uuid4(),)
        )
        assert ProjectionState(store).observe(c).status == "CURRENT"
        raise RuntimeError("abort")
    assert ProjectionState(store).observe().status == "ERROR"


def test_observation_rejects_autocommit_connection(store):
    with store.connect() as c:
        with pytest.raises(ValueError, match="active PostgreSQL transaction"):
            ProjectionState(store).observe(c)
