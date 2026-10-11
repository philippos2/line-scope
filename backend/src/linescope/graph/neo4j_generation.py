"""Build and verify a fresh Graph generation without publishing the PG pointer.

The caller owns leader/exclusive mutation locks. Explicit Neo4j transactions
have a hard timeout; no automatic retry, cleanup of old generations or API use.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from ..domain.canonical import normalize_uuid
from .neo4j_projection import (
    CREATE_EDGE,
    GraphGenerationUnavailable,
    ProjectionIntegrityError,
    edge_projection,
)
from .projection_payload import projection_payload_hash, validate_projection_payload
from .rebuild_snapshot import RebuildSnapshot
from .transaction_timeout import neo4j_transaction_timeout

NODE_TYPES = {"Equipment", "Process", "ProductionOperation", "Product", "InfrastructureResource"}


@dataclass(frozen=True)
class VerifiedGeneration:
    generation: str
    snapshot_hash: str
    node_count: int
    aggregate_count: int


@dataclass(frozen=True)
class GenerationValidation:
    """Committed build evidence, not proof of current PG/Graph synchronization."""

    generation: str
    snapshot_hash: str
    validated_at: datetime


def _properties(values):
    # Neo4j omits null properties; compare their actual physical representation.
    return {
        key: value.to_native() if hasattr(value, "to_native") else value
        for key, value in values.items()
        if value is not None
    }


class Neo4jGeneration:
    def __init__(self, driver, *, database="neo4j", timeout_seconds=10):
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Neo4j transaction timeout must be positive and finite")
        self.driver, self.database, self.timeout_seconds = driver, database, timeout_seconds

    def require_verified(self, *, generation, snapshot_hash, leadership):
        generation = normalize_uuid(generation)
        if (
            type(snapshot_hash) is not str
            or len(snapshot_hash) != 64
            or any(c not in "0123456789abcdef" for c in snapshot_hash)
        ):
            raise ValueError("A canonical source Snapshot hash is required")
        validation = self.observe_validation(generation=generation, leadership=leadership)
        if validation.snapshot_hash != snapshot_hash:
            raise ProjectionIntegrityError("Generation Snapshot hash does not match")

    def observe_validation(self, *, generation, leadership):
        """Read durable build evidence without inventing source counts or currentness."""
        generation = normalize_uuid(generation)
        leadership.require()
        with self.driver.session(database=self.database) as session:
            with session.begin_transaction(
                timeout=neo4j_transaction_timeout(leadership, self.timeout_seconds)
            ) as tx:
                markers = list(
                    tx.run(
                        "MATCH (g:LineScopeGeneration {generation:$generation}) "
                        "RETURN g.validated AS validated,g.snapshot_hash AS hash,g.validated_at AS at "
                        "LIMIT 2",
                        generation=generation,
                    )
                )
                if len(markers) > 1:
                    raise ProjectionIntegrityError("Ambiguous generation validation marker")
                if not markers or markers[0]["validated"] is not True or markers[0]["at"] is None:
                    raise GraphGenerationUnavailable("Verified Graph generation is unavailable")
                marker = markers[0]
                validated_at = marker["at"]
                validated_at = (
                    validated_at.to_native() if hasattr(validated_at, "to_native") else validated_at
                )
                if (
                    not isinstance(validated_at, datetime)
                    or validated_at.tzinfo is None
                    or validated_at.utcoffset() is None
                ):
                    raise ProjectionIntegrityError("Invalid generation validation time")
                digest = marker["hash"]
                if (
                    type(digest) is not str
                    or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                ):
                    raise ProjectionIntegrityError("Invalid generation Snapshot hash")
                leadership.require()
                tx.commit()
        leadership.require()
        return GenerationValidation(generation, digest, validated_at.astimezone(timezone.utc))

    def build(self, *, generation, snapshot, leadership):
        generation = normalize_uuid(generation)
        if not isinstance(snapshot, RebuildSnapshot):
            raise ValueError("A Rebuild source snapshot is required")
        snapshot = deepcopy(snapshot)
        nodes, edges, markers = {}, {}, {}
        for node in snapshot.nodes:
            if (
                set(node) != {"entity_type", "entity_id", "entity_version", "active"}
                or node["entity_type"] not in NODE_TYPES
                or type(node["entity_version"]) is not int
                or node["entity_version"] <= 0
                or type(node["active"]) is not bool
                or normalize_uuid(node["entity_id"]) != node["entity_id"]
            ):
                raise ValueError("Invalid Rebuild node")
            key = (node["entity_type"], node["entity_id"])
            if key in nodes:
                raise ValueError("Duplicate Rebuild node")
            nodes[key] = {"generation": generation, **node}
        for raw in snapshot.aggregates:
            payload = validate_projection_payload(raw)
            key = (payload["aggregate_type"], payload["aggregate_id"])
            if key in markers:
                raise ValueError("Duplicate Rebuild aggregate")
            kind, endpoints, properties = edge_projection(generation, payload, None)
            if (endpoints["source_type"], endpoints["source_id"]) not in nodes or (
                endpoints["target_type"],
                endpoints["target_id"],
            ) not in nodes:
                raise ProjectionIntegrityError("Rebuild endpoint is absent")
            properties["source_rebuild_id"] = generation
            edges[key] = (kind, endpoints, _properties(properties))
            markers[key] = {
                "generation": generation,
                "aggregate_type": key[0],
                "aggregate_id": key[1],
                "source_version": payload["aggregate_version"],
                "payload_hash": projection_payload_hash(payload),
                "source_rebuild_id": generation,
            }
        digest = snapshot.snapshot_hash
        leadership.require()
        with self.driver.session(database=self.database) as session:
            with session.begin_transaction(
                timeout=neo4j_transaction_timeout(leadership, self.timeout_seconds)
            ) as tx:
                occupied = tx.run(
                    "MATCH (n {generation:$generation}) RETURN count(n) AS count",
                    generation=generation,
                ).single(strict=True)["count"]
                if occupied:
                    raise ProjectionIntegrityError("Generation already exists")
                tx.run(
                    "CREATE (:LineScopeGeneration {generation:$generation,validated:false,snapshot_hash:$hash})",
                    generation=generation,
                    hash=digest,
                ).consume()
                for properties in nodes.values():
                    leadership.require()
                    tx.run(
                        "CREATE (n:LineScopeEntity) SET n=$properties", properties=properties
                    ).consume()
                for key, (kind, endpoints, properties) in edges.items():
                    leadership.require()
                    created = tx.run(
                        CREATE_EDGE[kind],
                        generation=generation,
                        **endpoints,
                        properties=properties,
                    ).single(strict=True)["created"]
                    if created != 1:
                        raise ProjectionIntegrityError("Rebuild endpoint is absent or ambiguous")
                    tx.run(
                        "CREATE (m:LineScopeProjectionMarker) SET m=$properties",
                        properties=markers[key],
                    ).consume()
                leadership.require()
                self._verify(tx, generation, nodes, edges, markers, digest)
                leadership.require()
                tx.run(
                    "MATCH (g:LineScopeGeneration {generation:$generation,validated:false}) "
                    "SET g.validated=true,g.validated_at=$validated_at",
                    generation=generation,
                    validated_at=datetime.now(timezone.utc),
                ).consume()
                leadership.require()
                tx.commit()
        leadership.require()
        return VerifiedGeneration(generation, digest, len(nodes), len(markers))

    @staticmethod
    def _verify(tx, generation, nodes, edges, markers, digest):
        generation_marker = tx.run(
            "MATCH (g:LineScopeGeneration {generation:$generation}) RETURN properties(g) AS properties",
            generation=generation,
        ).single(strict=True)
        if generation_marker is None or dict(generation_marker["properties"]) != {
            "generation": generation,
            "validated": False,
            "snapshot_hash": digest,
        }:
            raise ProjectionIntegrityError("Invalid generation verification marker")
        total = tx.run(
            "MATCH (n {generation:$generation}) RETURN count(n) AS count",
            generation=generation,
        ).single(strict=True)["count"]
        if total != 1 + len(nodes) + len(markers):
            raise ProjectionIntegrityError("Generation node count differs from Snapshot")
        actual_nodes = {}
        for row in tx.run(
            "MATCH (n:LineScopeEntity {generation:$generation}) RETURN properties(n) AS properties",
            generation=generation,
        ):
            props = dict(row["properties"])
            key = (props.get("entity_type"), props.get("entity_id"))
            if key in actual_nodes:
                raise ProjectionIntegrityError("Duplicate generation node")
            actual_nodes[key] = props
        actual_markers = {}
        for row in tx.run(
            "MATCH (m:LineScopeProjectionMarker {generation:$generation}) RETURN properties(m) AS properties",
            generation=generation,
        ):
            props = dict(row["properties"])
            key = (props.get("aggregate_type"), props.get("aggregate_id"))
            if key in actual_markers:
                raise ProjectionIntegrityError("Duplicate generation marker")
            actual_markers[key] = props
        actual_edges = {}
        for row in tx.run(
            "MATCH (s)-[r]->(t) WHERE r.generation=$generation "
            "RETURN type(r) AS kind,properties(r) AS properties,s.generation AS source_generation,"
            "t.generation AS target_generation,s.entity_type AS source_type,s.entity_id AS source_id,"
            "t.entity_type AS target_type,t.entity_id AS target_id",
            generation=generation,
        ):
            if row["source_generation"] != generation or row["target_generation"] != generation:
                raise ProjectionIntegrityError("Cross-generation edge")
            props = _properties(dict(row["properties"]))
            key = (
                "ProductionOperationEquipmentAssignment"
                if row["kind"] == "USES"
                else "DependencyRelation",
                props.get("source_record_id"),
            )
            if key in actual_edges:
                raise ProjectionIntegrityError("Duplicate generation edge")
            endpoints = {
                field: row[field]
                for field in ("source_type", "source_id", "target_type", "target_id")
            }
            actual_edges[key] = (row["kind"], endpoints, props)
        if actual_nodes != nodes or actual_edges != edges or actual_markers != markers:
            raise ProjectionIntegrityError("Generation differs from the source Snapshot")
