"""Internal dependency Prepare: consistent SoR read and immutable proposal save."""

import re

from .canonical import canonical_hash, canonical_json, normalize_timestamp, normalize_uuid
from .dependency_cycles import DependencyCycleError, validate_dependency_cycles
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .relations import (
    ENDPOINTS,
    INPUT_FIELDS,
    KEY_FIELDS,
    MAX_VERSION,
    RelationSetConflict,
    _record,
    dependency_relation_create_target,
    dependency_relation_target,
    normalize_relation_set,
)
from .snapshot import build_dependency_relation_snapshot

ENTITY_TYPES = {"Equipment", "Process", "ProductionOperation", "Product", "InfrastructureResource"}
# One statement, including inactive records and all periods; no business locks.
OBSERVE = """
SELECT
 COALESCE((SELECT jsonb_agg(to_jsonb(r)-'created_at'-'updated_at') FROM dependency_relation r), '[]'::jsonb) AS relations,
 COALESCE((SELECT jsonb_agg(to_jsonb(a)-'created_at'-'updated_at') FROM production_operation_equipment_assignment a), '[]'::jsonb) AS assignments,
 COALESCE((SELECT jsonb_agg(to_jsonb(e)) FROM (
   SELECT 'Equipment' AS entity_type,equipment_id AS entity_id,active FROM equipment
   UNION ALL SELECT 'Process',process_id,active FROM process
   UNION ALL SELECT 'ProductionOperation',production_operation_id,active FROM production_operation
   UNION ALL SELECT 'Product',product_id,active FROM product
   UNION ALL SELECT 'InfrastructureResource',infrastructure_resource_id,active FROM infrastructure_resource
 ) e), '[]'::jsonb) AS endpoints
"""


def _input(target):
    if type(target) is not dict:
        raise ValueError("Dependency input must be a record")
    operation = target.get("operation_type")
    if type(operation) is not str or operation not in {"CREATE", "UPDATE", "DISABLE"}:
        raise ValueError("Invalid dependency operation")
    fields = (
        {"operation_type"} | INPUT_FIELDS
        if operation == "CREATE"
        else {"operation_type", "dependency_relation_id"}
        | ({"patch"} if operation == "UPDATE" else set())
    )
    if set(target) != fields:
        raise ValueError("Invalid dependency input fields")
    values = (
        {field: target[field] for field in INPUT_FIELDS}
        if operation == "CREATE"
        else target.get("patch", {})
    )
    if (
        type(values) is not dict
        or not set(values) <= INPUT_FIELDS
        or (operation == "UPDATE" and not values)
    ):
        raise ValueError("Invalid dependency patch")
    normalized = {}
    for field, value in values.items():
        if field in {"source_entity_id", "target_entity_id"}:
            normalized[field] = normalize_uuid(value)
        elif field in {"effective_from", "effective_to"}:
            normalized[field] = (
                None if field == "effective_to" and value is None else normalize_timestamp(value)
            )
        elif field in {"active", "required"}:
            if type(value) is not bool:
                raise ValueError("Dependency flags must be boolean")
            normalized[field] = value
        else:
            allowed = ENDPOINTS if field == "relation_type" else ENTITY_TYPES
            if type(value) is not str or value not in allowed:
                raise ValueError("Unsupported relation or endpoint type")
            normalized[field] = value
    result = {"operation_type": operation}
    if operation == "CREATE":
        result.update(normalized)
    else:
        result["dependency_relation_id"] = normalize_uuid(target["dependency_relation_id"])
        if operation == "UPDATE":
            result["patch"] = normalized
    return result


def _input_key(target):
    if target["operation_type"] == "CREATE":
        return ("CREATE", canonical_json({field: target[field] for field in KEY_FIELDS}))
    return (target["operation_type"], target["dependency_relation_id"])


class DependencyPrepare:
    def __init__(self, database):
        self.store = ProposalStore(database)

    def prepare(
        self, context, targets, retry_key, *, agent_input_hash, supersedes_update_request_id=None
    ):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if context.role not in REQUEST_ROLES["DEPENDENCY"]:
            raise ProposalError("AUTHORIZATION_DENIED", "Dependency request permission is required")
        try:
            if type(agent_input_hash) is not str or not re.fullmatch(
                r"[0-9a-f]{64}", agent_input_hash
            ):
                raise ValueError("Normalized Agent input hash is required")
            if type(targets) is not list or not targets:
                raise ValueError("Targets must be a nonempty array")
            normalized = sorted((_input(target) for target in targets), key=_input_key)
            replacement = (
                normalize_uuid(supersedes_update_request_id)
                if supersedes_update_request_id is not None
                else None
            )
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid dependency Prepare input") from error
        ids = [
            target["dependency_relation_id"]
            for target in normalized
            if target["operation_type"] != "CREATE"
        ]
        create_keys = [
            _input_key(target) for target in normalized if target["operation_type"] == "CREATE"
        ]
        if len(set(ids)) != len(ids) or len(set(create_keys)) != len(create_keys):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Duplicate dependency target")
        input_hash = canonical_hash(
            {
                "prepare_tool": "prepare_dependency_relation_update",
                "targets": normalized,
                "supersedes_update_request_id": replacement,
            }
        )
        replay = self.store.find_by_retry(
            context, retry_key, prepare_input_hash=input_hash, agent_input_hash=agent_input_hash
        )
        if replay is not None:
            return replay
        with self.store._transaction(read_only=True) as connection:
            observed = connection.execute(OBSERVE).fetchone()
        try:
            records = [_record(row) for row in observed["relations"]]
            current = {row["dependency_relation_id"]: row for row in records}
        except ValueError as error:
            raise ProposalError("INTERNAL_ERROR", "Current dependency record is invalid") from error
        if set(ids) - current.keys():
            raise ProposalError("TARGET_NOT_FOUND", "Dependency target was not found")
        endpoints = {
            (row["entity_type"], row["entity_id"]): row["active"] for row in observed["endpoints"]
        }
        prepared = []
        # Validate all supplied values and endpoints before allocating CREATE IDs.
        for target in normalized:
            operation = target["operation_type"]
            if operation == "CREATE":
                values = {field: target[field] for field in INPUT_FIELDS}
                candidate = {
                    **values,
                    "dependency_relation_id": "00000000-0000-0000-0000-000000000000",
                    "version": 1,
                }
            else:
                before = current[target["dependency_relation_id"]]
                if before["version"] == MAX_VERSION:
                    raise ProposalError(
                        "INTERNAL_ERROR", "Dependency version cannot be incremented"
                    )
                if operation == "DISABLE":
                    if not before["active"]:
                        raise ProposalError(
                            "BUSINESS_RULE_VIOLATION", "Dependency is already inactive"
                        )
                    values = {"active": False}
                else:
                    values = target["patch"]
                    if all(before[field] == value for field, value in values.items()):
                        raise ProposalError("BUSINESS_RULE_VIOLATION", "Dependency must change")
                candidate = {**before, **values, "version": before["version"] + 1}
            try:
                candidate = _record(candidate)
            except ValueError as error:
                raise ProposalError(
                    "BUSINESS_RULE_VIOLATION", "Dependency business values are invalid"
                ) from error
            for side in ("source", "target"):
                key = (candidate[f"{side}_entity_type"], candidate[f"{side}_entity_id"])
                if key not in endpoints:
                    raise ProposalError("TARGET_NOT_FOUND", "Dependency endpoint was not found")
                if not endpoints[key]:
                    raise ProposalError(
                        "BUSINESS_RULE_VIOLATION", "Dependency endpoint is inactive"
                    )
            prepared.append((target, values))
        changes = []
        final = dict(current)
        for target, values in prepared:
            try:
                if target["operation_type"] == "CREATE":
                    change = dependency_relation_create_target(values)
                    if change["target_id"] in final:
                        raise ProposalError("INTERNAL_ERROR", "Generated dependency ID collision")
                else:
                    change = dependency_relation_target(
                        current[target["dependency_relation_id"]],
                        None if target["operation_type"] == "DISABLE" else values,
                        operation_type=target["operation_type"],
                    )
            except ValueError as error:
                raise ProposalError(
                    "INTERNAL_ERROR", "Dependency target construction failed"
                ) from error
            changes.append(change)
            final[change["target_id"]] = change["after"]
        try:
            final_rows = normalize_relation_set(list(final.values()))
            validate_dependency_cycles(final_rows, observed["assignments"])
        except (RelationSetConflict, DependencyCycleError) as error:
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Final dependency set violates business rules"
            ) from error
        except ValueError as error:
            raise ProposalError(
                "INTERNAL_ERROR", "Dependency validation source is invalid"
            ) from error
        snapshot = build_dependency_relation_snapshot(context, changes, replacement)
        return self.store.save(
            context,
            snapshot,
            retry_key,
            prepare_input_hash=input_hash,
            agent_input_hash=agent_input_hash,
        )
