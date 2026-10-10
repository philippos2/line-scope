"""Append projection events to the caller's Graph-affecting Execute transaction.

Caller duties: exclusive Graph mutation lock before row locks, approved saved
Snapshot verification, business updates and final-set validation. This helper
does not commit, retry conflicts, consume Approval, or run a Projection worker.
"""

from uuid import uuid4

from psycopg.types.json import Jsonb

from .assignments import validate_assignment_target
from .canonical import canonical_json, normalize_uuid
from .graph_locks import require_read_committed_transaction
from .projection_payload import build_projection_payload
from .relations import validate_relation_target


def enqueue_graph_target(connection, update_request_id, target):
    require_read_committed_transaction(connection)
    request_id = normalize_uuid(update_request_id)
    if type(target) is not dict:
        raise ValueError("A saved Graph target is required")
    validators = {
        "DependencyRelation": validate_relation_target,
        "ProductionOperationEquipmentAssignment": validate_assignment_target,
    }
    target_type = target.get("target_type")
    if type(target_type) is not str or target_type not in validators:
        raise ValueError("Unsupported Graph target")
    normalized = validators[target_type](target)
    row = connection.execute(
        "SELECT update_target_id,target_type,target_id,business_key,operation_type,"
        "before_snapshot,proposed_snapshot,expected_version FROM update_target "
        "WHERE update_request_id=%s AND target_type=%s AND target_id=%s",
        (request_id, target_type, normalized["target_id"]),
    ).fetchone()
    if row is None:
        raise ValueError("Graph target does not belong to the saved request")
    saved_target = {
        "target_type": row["target_type"],
        "target_id": str(row["target_id"]),
        "business_key": row["business_key"],
        "operation_type": row["operation_type"],
        "before": row["before_snapshot"],
        "after": row["proposed_snapshot"],
        "expected_version": row["expected_version"],
    }
    if canonical_json(saved_target) != canonical_json(normalized):
        raise ValueError("Graph target disagrees with the saved request")
    payload = build_projection_payload(target_type, normalized["after"])
    outbox_id = uuid4()
    connection.execute(
        "INSERT INTO graph_outbox(outbox_id,update_request_id,update_target_id,"
        "aggregate_type,aggregate_id,aggregate_version,event_type,payload) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            outbox_id,
            request_id,
            row["update_target_id"],
            target_type,
            payload["aggregate_id"],
            payload["aggregate_version"],
            normalized["operation_type"],
            Jsonb(payload),
        ),
    )
    return outbox_id
