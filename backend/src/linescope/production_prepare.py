"""Internal production schedule and assignment Prepare; no business DB writes."""

import re

from .assignments import normalize_operation_assignments
from .canonical import canonical_hash, normalize_id_set, normalize_timestamp, normalize_uuid
from .dependency_cycles import DependencyCycleError, validate_dependency_cycles
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .snapshot import (
    MAX_VERSION,
    OPERATION_PATCH_FIELDS,
    build_production_operation_snapshot,
    production_operation_assignment_targets,
    production_operation_target,
)


class ProductionPrepare:
    """Read consistent current rows and save a single-category production proposal."""

    allow_assignments = True

    def __init__(self, database):
        self.store = ProposalStore(database)

    def prepare(
        self, context, targets, retry_key, *, agent_input_hash, supersedes_update_request_id=None
    ):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if context.role not in REQUEST_ROLES["PRODUCTION_OPERATION"]:
            raise ProposalError("AUTHORIZATION_DENIED", "Production request permission is required")
        try:
            if type(agent_input_hash) is not str or not re.fullmatch(
                r"[0-9a-f]{64}", agent_input_hash
            ):
                raise ValueError("A normalized Agent input hash is required")
            if type(targets) is not list or not targets:
                raise ValueError("Targets must be a nonempty array")
            normalized = []
            for target in targets:
                allowed = {"production_operation_id", "patch"}
                if self.allow_assignments:
                    allowed.add("assignment_replacement")
                if (
                    type(target) is not dict
                    or not set(target) <= allowed
                    or "production_operation_id" not in target
                    or not set(target) & {"patch", "assignment_replacement"}
                ):
                    raise ValueError("Invalid production input")
                patch = target.get("patch")
                if "patch" in target and (
                    type(patch) is not dict or not patch or not set(patch) <= OPERATION_PATCH_FIELDS
                ):
                    raise ValueError("Invalid production schedule patch")
                values = {}
                for field, value in (patch or {}).items():
                    if field == "planned_status":
                        if type(value) is not str or value not in {"PLANNED", "CANCELLED"}:
                            raise ValueError("Invalid planned status")
                        values[field] = value
                    else:
                        values[field] = normalize_timestamp(value)
                item = {
                    "production_operation_id": normalize_uuid(target["production_operation_id"])
                }
                if "patch" in target:
                    item["patch"] = values
                if "assignment_replacement" in target:
                    assignment = target["assignment_replacement"]
                    if type(assignment) is not dict or set(assignment) != {
                        "effective_from",
                        "effective_to",
                        "equipment_ids",
                    }:
                        raise ValueError("Invalid assignment replacement")
                    start = normalize_timestamp(assignment["effective_from"])
                    end = (
                        normalize_timestamp(assignment["effective_to"])
                        if assignment["effective_to"] is not None
                        else None
                    )
                    item["assignment_replacement"] = {
                        "effective_from": start,
                        "effective_to": end,
                        "equipment_ids": normalize_id_set(assignment["equipment_ids"]),
                    }
                normalized.append(item)
            replacement = (
                normalize_uuid(supersedes_update_request_id)
                if supersedes_update_request_id is not None
                else None
            )
            normalized.sort(key=lambda target: target["production_operation_id"])
            input_hash = canonical_hash(
                {
                    "prepare_tool": "prepare_production_operation_update",
                    "targets": normalized,
                    "supersedes_update_request_id": replacement,
                }
            )
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid production Prepare input") from error
        ids = [target["production_operation_id"] for target in normalized]
        if len(set(ids)) != len(ids):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Duplicate production operation target")
        replay = self.store.find_by_retry(
            context, retry_key, prepare_input_hash=input_hash, agent_input_hash=agent_input_hash
        )
        if replay is not None:
            return replay
        assignment_changes = any("assignment_replacement" in item for item in normalized)
        equipment = set()
        if assignment_changes:
            equipment = {
                identifier
                for item in normalized
                for identifier in item.get("assignment_replacement", {}).get("equipment_ids", [])
            }
        with self.store._transaction(read_only=True) as connection:
            if assignment_changes:
                observed = connection.execute(
                    "SELECT "
                    "COALESCE((SELECT jsonb_agg(to_jsonb(p)-'created_at'-'updated_at') "
                    "FROM production_operation p WHERE production_operation_id=ANY(%s::uuid[])), '[]'::jsonb) AS operations, "
                    "COALESCE((SELECT jsonb_agg(to_jsonb(a)-'created_at'-'updated_at') "
                    "FROM production_operation_equipment_assignment a), '[]'::jsonb) AS assignments, "
                    "COALESCE((SELECT jsonb_agg(to_jsonb(r)-'created_at'-'updated_at') "
                    "FROM dependency_relation r), '[]'::jsonb) AS relations, "
                    "ARRAY(SELECT equipment_id FROM equipment WHERE equipment_id=ANY(%s::uuid[])) AS equipment_ids",
                    (ids, sorted(equipment)),
                ).fetchone()
                rows = observed["operations"]
            else:
                rows = connection.execute(
                    "SELECT production_operation_id,operation_code,process_id,planned_status,"
                    "planned_start,planned_end,active,version FROM production_operation "
                    "WHERE production_operation_id=ANY(%s::uuid[])",
                    (ids,),
                ).fetchall()
        current = {str(row["production_operation_id"]): row for row in rows}
        if len(current) != len(ids):
            raise ProposalError("TARGET_NOT_FOUND", "Production operation target was not found")
        if assignment_changes:
            if equipment - {str(identifier) for identifier in observed["equipment_ids"]}:
                raise ProposalError("TARGET_NOT_FOUND", "Assignment equipment was not found")
            for item in normalized:
                assignment = item.get("assignment_replacement")
                if (
                    assignment
                    and assignment["effective_to"] is not None
                    and assignment["effective_from"] >= assignment["effective_to"]
                ):
                    raise ProposalError(
                        "BUSINESS_RULE_VIOLATION", "Assignment interval must be nonempty"
                    )
            try:
                by_operation = {}
                for assignment in observed["assignments"]:
                    by_operation.setdefault(assignment["production_operation_id"], []).append(
                        assignment
                    )
                source_assignments = [
                    row
                    for operation_id, group in by_operation.items()
                    for row in normalize_operation_assignments(operation_id, group)
                ]
                final_assignments = {row["assignment_id"]: row for row in source_assignments}
            except ValueError as error:
                raise ProposalError("INTERNAL_ERROR", "Current assignments are invalid") from error
        changes = []
        for target in normalized:
            row = dict(current[target["production_operation_id"]])
            try:
                row["planned_start"] = normalize_timestamp(row["planned_start"])
                row["planned_end"] = normalize_timestamp(row["planned_end"])
                if not 1 <= row["version"] < MAX_VERSION:
                    raise ValueError("Current version cannot be incremented")
            except ValueError as error:
                raise ProposalError(
                    "INTERNAL_ERROR", "Production current value is invalid"
                ) from error
            patch = target.get("patch", {})
            after = {**row, **patch}
            if after["planned_start"] >= after["planned_end"]:
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Production start must precede end")
            if "patch" in target and all(row[field] == value for field, value in patch.items()):
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Production schedule must change")
            try:
                if "assignment_replacement" in target:
                    operation_changes = production_operation_assignment_targets(
                        row,
                        by_operation.get(target["production_operation_id"], []),
                        target["assignment_replacement"],
                        target.get("patch"),
                    )
                    changes.extend(operation_changes)
                    for diff in operation_changes[1:]:
                        if (
                            diff["operation_type"] == "CREATE"
                            and diff["target_id"] in final_assignments
                        ):
                            raise ValueError("Generated assignment ID collision")
                        final_assignments[diff["target_id"]] = diff["after"]
                else:
                    changes.append(production_operation_target(row, patch))
            except ValueError as error:
                code = (
                    "BUSINESS_RULE_VIOLATION" if "must change" in str(error) else "INTERNAL_ERROR"
                )
                raise ProposalError(code, "Production proposal could not be constructed") from error
        if assignment_changes:
            try:
                final_groups = {}
                for assignment in final_assignments.values():
                    final_groups.setdefault(assignment["production_operation_id"], []).append(
                        assignment
                    )
                for operation_id, group in final_groups.items():
                    normalize_operation_assignments(operation_id, group)
                validate_dependency_cycles(observed["relations"], list(final_assignments.values()))
            except ValueError as error:
                code = (
                    "BUSINESS_RULE_VIOLATION"
                    if isinstance(error, DependencyCycleError)
                    else "INTERNAL_ERROR"
                )
                raise ProposalError(code, "Production dependency validation failed") from error
        snapshot = build_production_operation_snapshot(context, changes, replacement)
        return self.store.save(
            context,
            snapshot,
            retry_key,
            prepare_input_hash=input_hash,
            agent_input_hash=agent_input_hash,
        )


class ProductionSchedulePrepare(ProductionPrepare):
    """Compatibility entry retaining the schedule-only schema and retry hashes."""

    allow_assignments = False
