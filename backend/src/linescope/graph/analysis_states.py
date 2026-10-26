"""Authoritative equipment/operation state observation under the caller's Graph lock."""

import psycopg

from ..application.reads import ToolError
from ..persistence.core_reads import get_graph_availability_states, get_graph_equipment_states
from .postgres_timeout import cap_postgres_transaction


class GraphStateReader:
    def __init__(self, database):
        self.database = database.for_reads()

    def read(self, identifiers, budget):
        return self._observe(
            lambda connection: get_graph_equipment_states(connection, identifiers), budget
        )

    def read_availability(self, equipment_ids, operation_ids, budget, *, resource_ids=()):
        return self._observe(
            lambda connection: get_graph_availability_states(
                connection, equipment_ids, operation_ids, resource_ids
            ),
            budget,
        )

    def _observe(self, query, budget):
        try:
            budget.require()
            with self.database.connect() as connection:
                connection.read_only = True
                with connection.transaction():
                    cap_postgres_transaction(connection, budget)
                    row = query(connection)
                    budget.require()
            budget.require()
            return row
        except (
            psycopg.errors.LockNotAvailable,
            psycopg.errors.QueryCanceled,
            TimeoutError,
        ) as error:
            raise ToolError("RESOURCE_BUSY", "Graph state observation timed out") from error
        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "PostgreSQL is unavailable") from error
        except psycopg.Error as error:
            raise ToolError("INTERNAL_ERROR", "Graph state observation failed") from error
