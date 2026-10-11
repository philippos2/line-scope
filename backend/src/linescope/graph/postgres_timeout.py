"""Cap the caller-owned Rebuild transaction without extending existing limits."""

from contextlib import contextmanager
from math import isfinite

from ..persistence.core_timeouts import read_timeout_limits, set_local_timeout_limits
from .graph_locks import require_read_committed_transaction
from .transaction_timeout import GraphTransactionBudgetExpired


def cap_postgres_transaction(connection, leadership):
    leadership.require()
    require_read_committed_transaction(connection)
    current = read_timeout_limits(connection)
    # Recompute after reading current settings, before changing local limits.
    remaining = leadership.remaining()
    if type(remaining) not in (int, float) or not isfinite(remaining) or remaining <= 0:
        raise GraphTransactionBudgetExpired("Invalid or expired PostgreSQL transaction budget")
    budget_ms = int(remaining * 1000)
    if budget_ms < 1:
        raise GraphTransactionBudgetExpired("No positive PostgreSQL transaction budget remains")
    limits = {
        name: min(value, budget_ms) if value else budget_ms for name, value in current.items()
    }
    set_local_timeout_limits(
        connection, statement_ms=limits["statement_timeout"], lock_ms=limits["lock_timeout"]
    )
    leadership.require()


@contextmanager
def postgres_budget_transaction(database, leadership):
    """Own a short transaction; normal leaders retain configured limits."""
    with database.transaction() as connection:
        if hasattr(leadership, "remaining"):
            cap_postgres_transaction(connection, leadership)
        yield connection
