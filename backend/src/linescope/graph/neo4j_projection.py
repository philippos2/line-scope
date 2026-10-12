"""Atomic edge Projection on a caller-owned official Neo4j driver.

Normal worker only: schema and validated generations/endpoints must already
exist. No implicit retries, Graph seed, arbitrary Cypher, or HTTP/Tool exposure.
"""

from datetime import datetime
from math import isfinite

from ..domain.canonical import normalize_uuid
from ..domain.relations import ENDPOINTS
from .projection_payload import projection_payload_hash, validate_projection_payload
from .transaction_timeout import neo4j_transaction_timeout

SCHEMA = (
    "CREATE CONSTRAINT linescope_entity_identity IF NOT EXISTS "
    "FOR (n:LineScopeEntity) REQUIRE (n.generation,n.entity_type,n.entity_id) IS UNIQUE",
    "CREATE CONSTRAINT linescope_projection_identity IF NOT EXISTS "
    "FOR (n:LineScopeProjectionMarker) "
    "REQUIRE (n.generation,n.aggregate_type,n.aggregate_id) IS UNIQUE",
    "CREATE CONSTRAINT linescope_generation_identity IF NOT EXISTS "
    "FOR (n:LineScopeGeneration) REQUIRE n.generation IS UNIQUE",
)
# Identifiers come only from this closed, module-owned map. All data is bound.
CREATE_EDGE = {
    kind: "MATCH (s:LineScopeEntity {generation:$generation,entity_type:$source_type,"
    "entity_id:$source_id}), (t:LineScopeEntity {generation:$generation,"
    "entity_type:$target_type,entity_id:$target_id}) "
    f"CREATE (s)-[r:{kind}]->(t) SET r = $properties RETURN count(r) AS created"
    for kind in (*ENDPOINTS, "USES")
}


class ProjectionIntegrityError(ValueError):
    """Projection facts/marker are inconsistent; never acknowledge success."""


class GraphGenerationUnavailable(RuntimeError):
    """The target generation has not been verified and published for use."""


def install_projection_schema(driver, *, database="neo4j", timeout_seconds=10):
    """Admin-only setup; never called from normal event application."""
    timeout = neo4j_transaction_timeout(None, timeout_seconds)
    with driver.session(database=database) as session:
        for statement in SCHEMA:
            with session.begin_transaction(timeout=timeout) as transaction:
                transaction.run(statement).consume()
                transaction.commit()


class Neo4jProjection:
    def __init__(self, driver, *, database="neo4j", timeout_seconds=10):
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Neo4j transaction timeout must be positive and finite")
        self.driver = driver
        self.database = database
        self.timeout_seconds = timeout_seconds

    def apply(self, *, generation, outbox_id, payload, leadership):
        generation = normalize_uuid(generation)
        outbox_id = normalize_uuid(outbox_id)
        payload = validate_projection_payload(payload)
        digest = projection_payload_hash(payload)
        parameters = {
            "generation": generation,
            "aggregate_type": payload["aggregate_type"],
            "aggregate_id": payload["aggregate_id"],
        }
        leadership.require()
        # Explicit transaction: retry belongs to the PG Outbox lifecycle.
        with self.driver.session(database=self.database) as session:
            with session.begin_transaction(
                timeout=neo4j_transaction_timeout(leadership, self.timeout_seconds)
            ) as tx:
                ready = tx.run(
                    "MATCH (g:LineScopeGeneration {generation:$generation,validated:true}) "
                    "RETURN g.generation AS generation,g.snapshot_hash AS hash",
                    generation=generation,
                ).single()
                if ready is None:
                    raise GraphGenerationUnavailable("Verified Graph generation is unavailable")
                leadership.require()
                marker_result = tx.run(
                    "MERGE (m:LineScopeProjectionMarker {generation:$generation,"
                    "aggregate_type:$aggregate_type,aggregate_id:$aggregate_id}) "
                    "SET m._projection_lock=true REMOVE m._projection_lock "
                    "RETURN m.source_version AS version,m.payload_hash AS hash,"
                    "m.source_outbox_id AS outbox_id,m.source_rebuild_id AS rebuild_id",
                    **parameters,
                )
                marker = marker_result.single(strict=True)
                created = marker_result.consume().counters.nodes_created == 1
                version = 0 if created else marker["version"]
                if type(version) is not int or version < 0 or (version == 0 and not created):
                    raise ProjectionIntegrityError("Invalid Projection marker version")
                if version > 0:
                    if (
                        type(marker["hash"]) is not str
                        or len(marker["hash"]) != 64
                        or any(c not in "0123456789abcdef" for c in marker["hash"])
                    ):
                        raise ProjectionIntegrityError("Invalid Projection marker hash")
                    if marker["outbox_id"] is None:
                        if (
                            marker["rebuild_id"] != generation
                            or type(ready["hash"]) is not str
                            or len(ready["hash"]) != 64
                            or any(c not in "0123456789abcdef" for c in ready["hash"])
                        ):
                            raise ProjectionIntegrityError("Invalid Rebuild marker source")
                    else:
                        try:
                            normalize_uuid(marker["outbox_id"])
                        except ValueError as error:
                            raise ProjectionIntegrityError(
                                "Invalid Projection marker source"
                            ) from error
                        if marker["rebuild_id"] is not None:
                            raise ProjectionIntegrityError("Ambiguous Projection marker source")
                if version == payload["aggregate_version"] and marker["hash"] != digest:
                    raise ProjectionIntegrityError(
                        "Same version has a different Projection payload"
                    )
                if version < payload["aggregate_version"]:
                    leadership.require()
                    self._replace_edge(tx, parameters, payload, outbox_id)
                    leadership.require()
                    tx.run(
                        "MATCH (m:LineScopeProjectionMarker {generation:$generation,"
                        "aggregate_type:$aggregate_type,aggregate_id:$aggregate_id}) "
                        "SET m.source_version=$version,m.payload_hash=$hash,"
                        "m.source_outbox_id=$outbox_id REMOVE m.source_rebuild_id",
                        **parameters,
                        version=payload["aggregate_version"],
                        hash=digest,
                        outbox_id=outbox_id,
                    ).consume()
                leadership.require()
                tx.commit()
        leadership.require()

    def _replace_edge(self, tx, parameters, payload, outbox_id):
        relation = payload["aggregate_type"] == "DependencyRelation"
        kind, endpoints, properties = edge_projection(parameters["generation"], payload, outbox_id)
        # Record IDs belong to two aggregate namespaces; never remove USES
        # while replacing a DependencyRelation with the same UUID, or vice versa.
        tx.run(
            "MATCH ()-[r]->() WHERE r.generation=$generation "
            "AND r.source_record_id=$aggregate_id AND type(r) IN $types DELETE r",
            generation=parameters["generation"],
            aggregate_id=payload["aggregate_id"],
            types=list(ENDPOINTS) if relation else ["USES"],
        ).consume()
        created = tx.run(
            CREATE_EDGE[kind],
            generation=parameters["generation"],
            **endpoints,
            properties=properties,
        ).single(strict=True)["created"]
        if created != 1:
            raise ProjectionIntegrityError("Projection endpoint is absent or ambiguous")


def edge_projection(generation, payload, outbox_id):
    """Shared physical edge mapping for already validated worker/Rebuild payloads."""
    state = payload["state"]
    relation = payload["aggregate_type"] == "DependencyRelation"
    kind = state["relation_type"] if relation else "USES"
    endpoints = {
        "source_type": state["source_entity_type"] if relation else "ProductionOperation",
        "source_id": state["source_entity_id"] if relation else state["production_operation_id"],
        "target_type": state["target_entity_type"] if relation else "Equipment",
        "target_id": state["target_entity_id"] if relation else state["equipment_id"],
    }
    properties = {
        "generation": generation,
        "source_record_id": payload["aggregate_id"],
        "source_version": payload["aggregate_version"],
        "source_outbox_id": outbox_id,
        "effective_from": datetime.fromisoformat(state["effective_from"]),
        "effective_to": datetime.fromisoformat(state["effective_to"])
        if state["effective_to"] is not None
        else None,
        "active": state["active"],
    }
    if relation:
        properties["required"] = state["required"]
    return kind, endpoints, properties
