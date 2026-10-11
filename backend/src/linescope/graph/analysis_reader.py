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
from ..domain.graph_paths import PathSelection, representative_paths
from ..domain.graph_reachability import LogicalEdge, Reachability, walk_reachability
from ..domain.graph_traversal import traversal_types
from ..domain.relations import ENDPOINTS
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


@dataclass(frozen=True)
class GraphAdjacency:
    edges: tuple[dict, ...]
    has_more: bool


@dataclass(frozen=True)
class GraphTraversal:
    reachability: Reachability
    paths: PathSelection
    edges: tuple[dict, ...]


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

    def neighbors(
        self, entity_type, entity_id, *, direction, as_of, limit, after=None, relation_types=None
    ):
        """Bounded one-hop facts; no transitive impact or availability inference."""
        if self._closed:
            raise RuntimeError("Graph read context is closed")
        if type(entity_type) is not str or entity_type not in NODE_TYPES:
            raise ValueError("Invalid Graph entity type")
        entity_id = normalize_uuid(entity_id)
        forward, reverse = traversal_types(direction)
        if relation_types is not None:
            if not relation_types or any(
                type(kind) is not str or kind not in forward | reverse for kind in relation_types
            ):
                raise ValueError("Invalid ordinary traversal filter")
            forward, reverse = forward & set(relation_types), reverse & set(relation_types)
        if type(limit) is not int or limit <= 0:
            raise ValueError("A positive server-owned adjacency limit is required")
        if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("An aware analysis time is required")
        if after is not None:
            if (
                type(after) is not tuple
                or len(after) != 3
                or type(after[0]) is not str
                or after[0] not in NODE_TYPES
                or normalize_uuid(after[1]) != after[1]
                or normalize_uuid(after[2]) != after[2]
            ):
                raise ValueError("Invalid server-owned adjacency continuation")
        after_type, after_id, after_record = after or (None, None, None)
        self._budget.require()
        rows = list(
            self._tx.run(
                "MATCH (s:LineScopeEntity)-[r]->(t:LineScopeEntity) "
                "WHERE s.generation=$generation AND t.generation=$generation "
                "AND r.generation=$generation AND s.active=true AND t.active=true AND r.active=true "
                "AND r.effective_from<=datetime($as_of) "
                "AND (r.effective_to IS NULL OR datetime($as_of)<r.effective_to) "
                "AND ((s.entity_type=$type AND s.entity_id=$id AND type(r) IN $forward) "
                "OR (t.entity_type=$type AND t.entity_id=$id AND type(r) IN $reverse)) "
                "WITH s,t,r,CASE WHEN type(r) IN $forward THEN t ELSE s END AS neighbor "
                "WHERE $has_after=false OR neighbor.entity_type>$after_type "
                "OR (neighbor.entity_type=$after_type AND neighbor.entity_id>$after_id) "
                "OR (neighbor.entity_type=$after_type AND neighbor.entity_id=$after_id "
                "AND r.source_record_id>$after_record) "
                "RETURN s.entity_type AS source_type,s.entity_id AS source_id,"
                "t.entity_type AS target_type,t.entity_id AS target_id,type(r) AS relation_type,"
                "r.source_record_id AS source_record_id,r.source_version AS source_version,"
                "r.required AS required,neighbor.entity_type AS neighbor_type,neighbor.entity_id AS neighbor_id "
                "ORDER BY neighbor_type,neighbor_id,source_record_id LIMIT $limit",
                generation=self.validation.generation,
                type=entity_type,
                id=entity_id,
                forward=sorted(forward),
                reverse=sorted(reverse),
                as_of=as_of.astimezone(timezone.utc).isoformat(),
                limit=limit + 1,
                has_after=after is not None,
                after_type=after_type,
                after_id=after_id,
                after_record=after_record,
            )
        )
        self._budget.require()
        edges = []
        for row in rows:
            edge = dict(row)
            if (
                edge["source_type"] not in NODE_TYPES
                or edge["target_type"] not in NODE_TYPES
                or type(edge["source_version"]) is not int
                or edge["source_version"] <= 0
                or (edge["relation_type"] != "USES" and type(edge["required"]) is not bool)
            ):
                raise ProjectionIntegrityError("Invalid Graph relation fact")
            allowed_source, allowed_target = (
                ({"ProductionOperation"}, {"Equipment"})
                if edge["relation_type"] == "USES"
                else ENDPOINTS[edge["relation_type"]]
            )
            if edge["source_type"] not in allowed_source or edge["target_type"] not in (
                allowed_target if allowed_target is not None else {edge["source_type"]}
            ):
                raise ProjectionIntegrityError("Invalid Graph relation endpoints")
            try:
                identifiers_valid = all(
                    normalize_uuid(edge[key]) == edge[key]
                    for key in ("source_id", "target_id", "source_record_id")
                )
            except ValueError as error:
                raise ProjectionIntegrityError("Invalid Graph relation identifier") from error
            if not identifiers_valid:
                raise ProjectionIntegrityError("Invalid Graph relation identifier")
            edges.append(edge)
        return GraphAdjacency(tuple(edges[:limit]), len(edges) > limit)

    def traverse(
        self,
        entity_type,
        entity_id,
        *,
        direction,
        as_of,
        max_depth,
        max_nodes,
        max_paths,
        page_size,
        relation_types=None,
        should_stop=None,
    ):
        """Internal multi-hop facts, in this context's single generation/tx.

        Deadline/driver failures propagate; no partial result bypasses the
        successful exit gate. Caller still owns authorization and public DTOs.
        """
        for limit in (max_depth, max_nodes, max_paths, page_size):
            if type(limit) is not int or limit <= 0:
                raise ValueError("Positive server-owned traversal limits are required")
        traversal_types(direction)
        root = self.node(entity_type, entity_id)
        if root is None or not root.active:
            raise ToolError("TARGET_NOT_FOUND", "Active Graph target was not found")
        facts = {}

        def neighbors(node):
            after = None
            while True:
                page = self.neighbors(
                    *node,
                    direction=direction,
                    as_of=as_of,
                    limit=page_size,
                    after=after,
                    relation_types=relation_types,
                )
                for fact in page.edges:
                    self._budget.require()
                    facts[fact["source_record_id"]] = fact
                    yield LogicalEdge(
                        node,
                        (fact["neighbor_type"], fact["neighbor_id"]),
                        fact["source_record_id"],
                    )
                if not page.has_more:
                    return
                last = page.edges[-1]
                after = (last["neighbor_type"], last["neighbor_id"], last["source_record_id"])

        reached = walk_reachability(
            (root.entity_type, root.entity_id),
            neighbors,
            max_depth=max_depth,
            max_nodes=max_nodes,
            should_stop=should_stop,
        )
        paths = representative_paths(reached, max_paths=max_paths)
        used = {identifier for path in paths.paths for identifier in path.source_record_ids}
        self._budget.require()
        return GraphTraversal(
            reached, paths, tuple(facts[identifier] for identifier in sorted(used))
        )


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
