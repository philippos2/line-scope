"""Real PG transaction-local budget caps, rollback and controller phase boundaries."""

from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest

from graph.test_neo4j_projection import graph_driver as graph_driver
from graph.test_rebuild_control import row
from graph.test_rebuild_controller import adapters as adapters
from graph.test_rebuild_controller import controller, logs
from graph.test_rebuild_controller import empty as empty
from graph.test_rebuild_drain import Clock
from linescope.graph.graph_leadership import graph_leadership
from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.postgres_timeout import cap_postgres_transaction
from linescope.graph.rebuild_drain import DeadlineLeadership
from linescope.graph.transaction_timeout import GraphTransactionBudgetExpired
from linescope.persistence.core_timeouts import read_timeout_limits
from linescope.persistence.database import Database


def guard(seconds):
    clock = Clock()
    leader = SimpleNamespace(require=lambda: None)
    return DeadlineLeadership(leader, clock.now + seconds, clock)


def test_caps_are_local_and_never_extend_existing_limits(empty):
    with empty.connect() as c:
        original = read_timeout_limits(c)
        with c.transaction():
            cap_postgres_transaction(c, guard(0.2))
            assert read_timeout_limits(c) == {"statement_timeout": 200, "lock_timeout": 200}
            cap_postgres_transaction(c, guard(3))
            assert read_timeout_limits(c) == {"statement_timeout": 200, "lock_timeout": 200}
        assert read_timeout_limits(c) == original


def test_unit_qualified_limits_and_unlimited_values_are_handled(empty):
    with empty.transaction() as c:
        c.execute(
            "SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
            ("2s", "0"),
        )
        cap_postgres_transaction(c, guard(0.25))
        assert read_timeout_limits(c) == {"statement_timeout": 250, "lock_timeout": 250}


def test_shorter_lock_limit_is_preserved(empty):
    with empty.transaction() as c:
        c.execute("SELECT set_config('lock_timeout',%s,true)", ("50ms",))
        cap_postgres_transaction(c, guard(0.2))
        assert read_timeout_limits(c) == {"statement_timeout": 200, "lock_timeout": 50}


@pytest.mark.parametrize("remaining", [0, -1, True, float("nan"), float("inf"), 0.0009])
def test_invalid_budget_does_not_change_limits(empty, remaining):
    leadership = SimpleNamespace(require=lambda: None, remaining=lambda: remaining)
    with empty.transaction() as c:
        before = read_timeout_limits(c)
        with pytest.raises(GraphTransactionBudgetExpired):
            cap_postgres_transaction(c, leadership)
        assert read_timeout_limits(c) == before


def test_requires_caller_owned_transaction(empty):
    with empty.connect() as c, pytest.raises(ValueError, match="active"):
        cap_postgres_transaction(c, guard(1))


def test_statement_timeout_rolls_back_work_and_restores_session_limits(empty):
    before = row(empty)
    with empty.connect() as c:
        original = read_timeout_limits(c)
        with pytest.raises(psycopg.errors.QueryCanceled), c.transaction():
            cap_postgres_transaction(c, guard(0.05))
            c.execute("UPDATE graph_projection_control SET fatal_error=%s", ("uncommitted",))
            c.execute("SELECT pg_sleep(%s)", (0.3,))
        assert read_timeout_limits(c) == original
    assert row(empty) == before


def test_controller_lock_wait_uses_remaining_budget_and_saves_failure(empty, adapters):
    contender = Database(replace(empty.settings, lock_ms=1000, statement_ms=2000))
    clock = Clock()
    service, output = controller(contender, adapters, timeout_ms=150, clock=clock, wait=clock.wait)
    with empty.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=True)
        with (
            graph_leadership(contender) as leader,
            pytest.raises((psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled)),
        ):
            service.run(leader)
    assert row(empty)["active_generation"] is None
    assert not row(empty)["rebuild_flag"] and row(empty)["fatal_error"] == "REBUILD_FAILED"
    assert logs(output)[-1]["outcome"] == "failure"
    with empty.transaction() as c:
        acquire_graph_mutation_lock(c, shared=True)


def test_snapshot_phase_recomputes_budget_on_same_lock_connection(empty, adapters, monkeypatch):
    import linescope.graph.rebuild_controller as module

    clock = Clock()
    original = module.read_rebuild_snapshot
    service, _ = controller(empty, adapters, timeout_ms=6000, clock=clock, wait=clock.wait)
    drain = service.drain.run
    seen = []

    def elapsed(*args, **kwargs):
        result = drain(*args, **kwargs)
        clock.now += 5
        return result

    def inspect(connection):
        seen.append(read_timeout_limits(connection))
        return original(connection)

    monkeypatch.setattr(service.drain, "run", elapsed)
    monkeypatch.setattr(module, "read_rebuild_snapshot", inspect)
    with graph_leadership(empty) as leader:
        service.run(leader)
    assert seen == [{"statement_timeout": 1000, "lock_timeout": 1000}]


def test_control_short_transactions_receive_guard_budget(empty, monkeypatch):
    import linescope.graph.rebuild_control as module

    control = module.RebuildControl(empty)
    seen = []
    original = module.cap_postgres_transaction

    def inspect(connection, leadership):
        original(connection, leadership)
        seen.append(read_timeout_limits(connection))

    monkeypatch.setattr(module, "cap_postgres_transaction", inspect)
    leadership = guard(0.2)
    ticket = control.begin(leadership)
    with empty.transaction() as lock:
        acquire_graph_mutation_lock(lock, shared=False)
        assert control.observe(leadership, lock).recovery_ticket() == ticket
        control.heartbeat(leadership, lock, ticket)
        replacement = control.resume(leadership, lock, ticket)
    assert replacement.rebuild_id != ticket.rebuild_id
    assert seen == [{"statement_timeout": 200, "lock_timeout": 200}] * 4
    assert control.fail(SimpleNamespace(require=lambda: None), replacement)
    assert len(seen) == 4


def test_control_begin_lock_timeout_preserves_committed_state(empty):
    from linescope.graph.rebuild_control import RebuildControl

    before = row(empty)
    with empty.transaction() as holder:
        holder.execute("SELECT * FROM graph_projection_control FOR UPDATE").fetchone()
        with pytest.raises((psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled)):
            RebuildControl(empty).begin(guard(0.1))
    assert row(empty) == before


def test_expired_control_guard_refuses_begin_without_state_change(empty):
    from linescope.graph.rebuild_control import RebuildControl

    before = row(empty)
    with pytest.raises(GraphTransactionBudgetExpired):
        RebuildControl(empty).begin(guard(0.0009))
    assert row(empty) == before


def test_controller_publication_short_transaction_recomputes_budget(empty, adapters, monkeypatch):
    import linescope.graph.rebuild_control as module

    clock = Clock()
    service, _ = controller(empty, adapters, timeout_ms=6000, clock=clock, wait=clock.wait)
    original = module.publish_rebuild
    build = service.generation.build
    seen = []

    def elapsed(**kwargs):
        result = build(**kwargs)
        clock.now += 5
        return result

    def inspect(connection, *args):
        seen.append(read_timeout_limits(connection))
        return original(connection, *args)

    monkeypatch.setattr(service.generation, "build", elapsed)
    monkeypatch.setattr(module, "publish_rebuild", inspect)
    with graph_leadership(empty) as leader:
        service.run(leader)
    assert seen == [{"statement_timeout": 1000, "lock_timeout": 1000}]
    assert not row(empty)["rebuild_flag"]
