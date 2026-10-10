"""Common transaction lock for Graph analysis, mutation, projection and Rebuild.

Callers own the connection/transaction and acquire this before business reads
or row locks. PostgreSQL lock/statement timeouts bound acquisition; exceptions
are mapped by each caller's existing storage boundary. This is not the worker
session leader lock or the migration lock.
"""

from psycopg.pq import TransactionStatus

GRAPH_MUTATION_LOCK = 0x4C534752415048  # Stable, distinct namespace: LSGRAPH.


def require_read_committed_transaction(connection):
    if connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("An active PostgreSQL transaction is required")
    row = connection.execute("SHOW transaction_isolation").fetchone()
    if row["transaction_isolation"] != "read committed":
        raise ValueError("Graph coordination requires READ COMMITTED isolation")


def acquire_graph_mutation_lock(connection, *, shared):
    """Acquire the fixed shared/exclusive key until transaction end.

    Never starts/commits a transaction, upgrades a caller's isolation, or
    releases a lock early. Session leader ownership remains a separate concern.
    """
    if type(shared) is not bool:
        raise ValueError("Graph lock mode must be a server boolean")
    require_read_committed_transaction(connection)
    statement = (
        "SELECT pg_advisory_xact_lock_shared(%s)" if shared else "SELECT pg_advisory_xact_lock(%s)"
    )
    connection.execute(statement, (GRAPH_MUTATION_LOCK,))
