"""PG-only analysis gate; callers still owe authorization and Neo4j validation.

Hold the shared mutation lock across Graph reading and server Evidence building.
Successful exit verifies CURRENT and the same generation; exceptions discard
results and release the transaction lock. This is not a public Graph Tool.
"""

from contextlib import contextmanager

import psycopg

from ..application.reads import ToolError
from .graph_locks import acquire_graph_mutation_lock
from .postgres_timeout import cap_postgres_transaction
from .projection_state import ProjectionState


class GraphAnalysisGate:
    def __init__(self, database):
        self.database = database.for_reads()
        self.state = ProjectionState(self.database)

    @contextmanager
    def open(self, budget):
        """Budget is server-owned; no leader lock or mutation authority is needed.

        Caller must complete its single-generation Neo4j read and Evidence
        inside this context, and expose results only after successful exit.
        PG CURRENT alone never proves a valid Neo4j generation marker.
        """
        try:
            budget.require()
            with self.database.connect() as connection:
                connection.read_only = True
                with connection.transaction():
                    cap_postgres_transaction(connection, budget)
                    acquire_graph_mutation_lock(connection, shared=True)
                    cap_postgres_transaction(connection, budget)
                    before = self.state.observe(connection)
                    self._current(before)
                    budget.require()
                    yield before
                    cap_postgres_transaction(connection, budget)
                    after = self.state.observe(connection)
                    self._current(after)
                    if after.active_generation != before.active_generation:
                        raise ToolError(
                            "GRAPH_NOT_CURRENT", "Graph generation changed during analysis"
                        )
                    budget.require()
            budget.require()
        except (
            psycopg.errors.LockNotAvailable,
            psycopg.errors.QueryCanceled,
            TimeoutError,
        ) as error:
            raise ToolError("RESOURCE_BUSY", "Graph analysis timed out") from error
        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "PostgreSQL is unavailable") from error
        except psycopg.Error as error:
            raise ToolError("INTERNAL_ERROR", "Graph analysis coordination failed") from error

    @staticmethod
    def _current(observation):
        codes = {
            "LAGGING": "GRAPH_NOT_CURRENT",
            "ERROR": "GRAPH_UNAVAILABLE",
            "REBUILDING": "GRAPH_REBUILDING",
        }
        if observation.status != "CURRENT":
            raise ToolError(
                codes.get(observation.status, "GRAPH_UNAVAILABLE"),
                "Graph is unavailable for analysis",
            )
