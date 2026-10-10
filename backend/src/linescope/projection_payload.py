"""Canonical edge-aggregate projection state, separate from delivery metadata.

Only existing mutable Graph aggregates are supported. Endpoint existence,
whole-set cycles/overlaps, DB locks and Neo4j application remain caller duties.
"""

from .assignments import normalize_operation_assignments
from .canonical import canonical_hash, canonical_json, strict_json
from .relations import normalize_relation_set

FIELDS = {"schema_version", "aggregate_type", "aggregate_id", "aggregate_version", "state"}


def build_projection_payload(aggregate_type, state):
    if type(state) is not dict:
        raise ValueError("Complete projection state is required")
    if aggregate_type == "DependencyRelation":
        row = normalize_relation_set([state])[0]
        identifier = row["dependency_relation_id"]
    elif aggregate_type == "ProductionOperationEquipmentAssignment":
        row = normalize_operation_assignments(state.get("production_operation_id"), [state])[0]
        identifier = row["assignment_id"]
    else:
        raise ValueError("Unsupported projection aggregate")
    return {
        "schema_version": 1,
        "aggregate_type": aggregate_type,
        "aggregate_id": identifier,
        "aggregate_version": row["version"],
        "state": row,
    }


def validate_projection_payload(payload):
    if type(payload) is not dict or set(payload) != FIELDS:
        raise ValueError("Invalid projection payload fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("Unsupported projection schema version")
    rebuilt = build_projection_payload(payload["aggregate_type"], payload["state"])
    # Compare canonical text, so Python bool/int equality cannot hide type drift.
    if canonical_json(rebuilt) != canonical_json(payload):
        raise ValueError("Projection payload is not normalized or disagrees with its state")
    return rebuilt


def projection_payload_hash(payload):
    return canonical_hash(validate_projection_payload(payload))


def load_projection_payload(text, expected_hash):
    payload = validate_projection_payload(strict_json(text))
    if type(expected_hash) is not str or projection_payload_hash(payload) != expected_hash:
        raise ValueError("Projection payload hash mismatch")
    return payload
