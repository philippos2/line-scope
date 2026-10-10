"""Internal PostgreSQL sync gate, not proof of a usable Neo4j projection.

Graph Tools must additionally hold the shared mutation lock, validate the
active Neo4j generation marker, and recheck this gate before returning results.
No HTTP route or LLM Tool exposes this storage observation yet.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg

from .reads import ToolError


@dataclass(frozen=True)
class ProjectionObservation:
    status: str
    active_generation: UUID | None
    observed_at: datetime
    counts: dict[str, int]


class ProjectionState:
    def __init__(self, database):
        self.database = database

    def observe(self):
        # Control and the entire committed event set share a statement snapshot.
        # Neither UUID ordering nor processed_at is a commit watermark.
        try:
            with self.database.transaction() as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
                row = c.execute(
                    "WITH events AS (SELECT "
                    "count(*) FILTER (WHERE status='PENDING') AS pending, "
                    "count(*) FILTER (WHERE status='PROCESSING') AS processing, "
                    "count(*) FILTER (WHERE status='RETRYABLE') AS retryable, "
                    "count(*) FILTER (WHERE status='APPLIED') AS applied, "
                    "count(*) FILTER (WHERE status='DEAD') AS dead FROM graph_outbox) "
                    "SELECT statement_timestamp() AS observed_at, c.control_id, "
                    "c.rebuild_flag,c.active_generation,c.fatal_error,events.* "
                    "FROM events LEFT JOIN graph_projection_control c ON c.control_id=1"
                ).fetchone()
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as error:
            raise ToolError("RESOURCE_BUSY", "Projection state observation timed out") from error
        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "PostgreSQL is unavailable") from error
        except psycopg.Error as error:
            raise ToolError("INTERNAL_ERROR", "Projection state observation failed") from error
        counts = {
            name.upper(): row[name]
            for name in ("pending", "processing", "retryable", "applied", "dead")
        }
        if row["rebuild_flag"]:
            status = "REBUILDING"
        elif (
            row["control_id"] is None
            or row["active_generation"] is None
            or row["fatal_error"] is not None
            or counts["DEAD"]
        ):
            status = "ERROR"
        elif any(counts[name] for name in ("PENDING", "PROCESSING", "RETRYABLE")):
            status = "LAGGING"
        else:
            status = "CURRENT"
        return ProjectionObservation(status, row["active_generation"], row["observed_at"], counts)
