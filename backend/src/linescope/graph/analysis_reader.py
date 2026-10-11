"""Verified, generation-scoped Graph reads under the PG shared analysis gate.

Internal adapter only: no HTTP/Tool exposure, arbitrary Cypher or authorization.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from neo4j import READ_ACCESS
from neo4j.exceptions import DriverError, Neo4jError

from ..application.reads import ToolError
from ..domain.canonical import normalize_uuid
from .analysis_gate import GraphAnalysisGate
from .neo4j_generation import NODE_TYPES, read_generation_validation
from .neo4j_projection import GraphGenerationUnavailable, ProjectionIntegrityError
from .transaction_timeout import neo4j_transaction_timeout


@dataclass(frozen=True)
class GraphNode:
    entity_type: str
    entity_id: str
    entity_version: int
    active: bool


class _GraphRead:
    def __init__(self, tx, budget, observation, validation):
        self._tx, self._budget = tx, budget
        self.observation, self.validation = observation, validation
        self.observed_at = datetime.now(timezone.utc)
        self._closed = False

    def node(self, entity_type, entity_id):
        """Read a typed registered node; active is not operational availability."""
        if self._closed:
            raise RuntimeError("Graph read context is closed")
        if type(entity_type) is not str or entity_type not in NODE_TYPES:
            raise ValueError("Invalid Graph entity type")
        entity_id = normalize_uuid(entity_id)
        self._budget.require()
        rows = list(
            self._tx.run(
                "MATCH (n:LineScopeEntity {generation:$generation,entity_type:$type,entity_id:$id}) "
                "RETURN n.entity_version AS version,n.active AS active LIMIT 2",
                generation=self.validation.generation,
                type=entity_type,
                id=entity_id,
            )
        )
        self._budget.require()
        if len(rows) > 1:
            raise ProjectionIntegrityError("Ambiguous Graph entity")
        if not rows:
            return None
        row = rows[0]
        if (
            type(row["version"]) is not int
            or row["version"] <= 0
            or type(row["active"]) is not bool
        ):
            raise ProjectionIntegrityError("Invalid Graph entity state")
        return GraphNode(entity_type, entity_id, row["version"], row["active"])


class GraphAnalysisReader:
    def __init__(self, database, driver, *, graph_database="neo4j", timeout_seconds=10):
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Neo4j transaction timeout must be positive and finite")
        self.gate = GraphAnalysisGate(database)
        self.driver, self.graph_database, self.timeout_seconds = (
            driver,
            graph_database,
            timeout_seconds,
        )

    @contextmanager
    def open(self, budget):
        """Expose results only after successful exit; do not retain this read context."""
        try:
            with self.gate.open(budget) as observation:
                with self.driver.session(
                    database=self.graph_database, default_access_mode=READ_ACCESS
                ) as session:
                    with session.begin_transaction(
                        timeout=neo4j_transaction_timeout(budget, self.timeout_seconds)
                    ) as tx:
                        validation = read_generation_validation(
                            tx, str(observation.active_generation)
                        )
                        budget.require()
                        read = _GraphRead(tx, budget, observation, validation)
                        try:
                            yield read
                            budget.require()
                            tx.commit()
                            budget.require()
                        finally:
                            read._closed = True
        except (
            GraphGenerationUnavailable,
            ProjectionIntegrityError,
            Neo4jError,
            DriverError,
        ) as error:
            raise ToolError("GRAPH_UNAVAILABLE", "Verified Graph read is unavailable") from error
