"""Dedicated session leadership shared by Projection workers and Rebuild controllers.

A leader context owns its connection for the entire operation. It must not be
pooled or reconnected: connection loss invalidates leadership. Callers acquire
this before the mutation lock and check ownership before further Graph work.
Neo4j cancellation and aggregate-marker serialization belong to its later adapter.
"""

from contextlib import contextmanager

import psycopg

GRAPH_LEADER_LOCK = 0x4C534C4541444552  # Stable, distinct namespace: LSLEADER.


class GraphLeaderBusy(RuntimeError):
    """Another worker or controller owns the session leader lock."""


class GraphLeadershipLost(RuntimeError):
    """The original session no longer owns leadership; further work must stop."""


class GraphLeadership:
    def __init__(self, connection):
        self._connection = connection

    def require(self):
        """Check the original session and lock without reacquiring or reconnecting."""
        if self._connection.closed:
            raise GraphLeadershipLost("Graph leadership session is closed")
        try:
            owned = self._connection.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                "AND pid=pg_backend_pid() AND classid=%s::oid AND objid=%s::oid "
                "AND objsubid=1 AND mode='ExclusiveLock' AND granted) AS owned",
                (GRAPH_LEADER_LOCK >> 32, GRAPH_LEADER_LOCK & 0xFFFFFFFF),
            ).fetchone()["owned"]
        except psycopg.Error as error:
            raise GraphLeadershipLost("Graph leadership session is unavailable") from error
        if not owned:
            raise GraphLeadershipLost("Graph leadership lock is no longer held")


@contextmanager
def graph_leadership(database):
    """Try leadership once on a new dedicated connection, closing it on every exit.

    A busy worker makes no progress and lets its caller schedule another attempt.
    Closing the connection releases all session locks, even on exceptions. No
    reconnect, automatic promotion or mutation-lock acquisition occurs here.
    """
    with database.connect() as connection:
        owned = connection.execute(
            "SELECT pg_try_advisory_lock(%s) AS owned", (GRAPH_LEADER_LOCK,)
        ).fetchone()["owned"]
        if not owned:
            raise GraphLeaderBusy("Graph leadership is held by another session")
        yield GraphLeadership(connection)
