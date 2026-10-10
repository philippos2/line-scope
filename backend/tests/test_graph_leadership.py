"""Real PostgreSQL session leadership, connection loss and lock independence."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from linescope.database import MIGRATION_LOCK
from linescope.graph_leadership import (
    GRAPH_LEADER_LOCK,
    GraphLeaderBusy,
    GraphLeadershipLost,
    graph_leadership,
)
from linescope.graph_locks import acquire_graph_mutation_lock


def test_competing_worker_and_controller_cannot_both_be_leader(db):
    with graph_leadership(db) as worker:
        worker.require()
        with pytest.raises(GraphLeaderBusy):
            with graph_leadership(db):
                pytest.fail("Second controller must not enter")
        worker.require()
    with graph_leadership(db) as controller:
        controller.require()


@pytest.mark.parametrize("rollback", [False, True])
def test_leader_survives_business_transaction_end(db, rollback):
    with graph_leadership(db) as leader:
        with db.connect() as business:
            with business.transaction():
                acquire_graph_mutation_lock(business, shared=False)
                if rollback:
                    raise psycopg.Rollback()
        leader.require()
        with pytest.raises(GraphLeaderBusy):
            with graph_leadership(db):
                pytest.fail("Business transaction end must not release leadership")


def test_dedicated_session_commit_and_rollback_do_not_release_leader(db):
    with graph_leadership(db) as leader:
        connection = leader._connection
        with connection.transaction():
            connection.execute("SELECT 1")
        leader.require()
        with pytest.raises(ValueError):
            with connection.transaction():
                connection.execute("SELECT 1")
                raise ValueError("force rollback")
        leader.require()
        with pytest.raises(GraphLeaderBusy):
            with graph_leadership(db):
                pytest.fail("Session leadership must survive rollback")


def test_exception_closes_dedicated_session_and_releases_leadership(db):
    with pytest.raises(ValueError):
        with graph_leadership(db) as leader:
            leader.require()
            raise ValueError("caller failed")
    assert leader._connection.closed
    with pytest.raises(GraphLeadershipLost):
        leader.require()
    with graph_leadership(db) as replacement:
        replacement.require()


def test_database_disconnect_invalidates_original_leader_and_allows_replacement(db):
    with graph_leadership(db) as old:
        pid = old._connection.info.backend_pid
        with db.connect() as other:
            assert other.execute("SELECT pg_terminate_backend(%s) AS stopped", (pid,)).fetchone()[
                "stopped"
            ]
        with pytest.raises(GraphLeadershipLost):
            old.require()
        with graph_leadership(db) as replacement:
            replacement.require()
            with pytest.raises(GraphLeadershipLost):
                old.require()


def test_missing_lock_is_not_silently_reacquired(db):
    with graph_leadership(db) as old:
        old._connection.execute("SELECT pg_advisory_unlock(%s)", (GRAPH_LEADER_LOCK,))
        with pytest.raises(GraphLeadershipLost):
            old.require()
        with graph_leadership(db) as replacement:
            replacement.require()
            with pytest.raises(GraphLeadershipLost):
                old.require()


def test_repeated_ownership_checks_do_not_add_reentrant_lock_depth(db):
    with graph_leadership(db) as leader:
        for _ in range(3):
            leader.require()
        assert leader._connection.execute(
            "SELECT pg_advisory_unlock(%s) AS released", (GRAPH_LEADER_LOCK,)
        ).fetchone()["released"]
        with graph_leadership(db) as replacement:
            replacement.require()


@pytest.mark.parametrize("shared", [False, True])
def test_leadership_is_independent_of_graph_mutation_and_migration_locks(db, shared):
    with db.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=shared)
        holder.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        with graph_leadership(db) as leader:
            leader.require()


def test_parallel_contenders_have_exactly_one_leader(db):
    start = Barrier(2)
    finish = Barrier(2)

    def contend(_):
        start.wait(timeout=5)
        try:
            with graph_leadership(db) as leader:
                leader.require()
                finish.wait(timeout=5)
                return True
        except GraphLeaderBusy:
            finish.wait(timeout=5)
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(contend, range(2))) == [False, True]
    with graph_leadership(db) as replacement:
        replacement.require()
