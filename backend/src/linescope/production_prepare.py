"""Internal schedule-only production Prepare; assignment changes are a later slice."""

import re

from .canonical import canonical_hash, normalize_timestamp, normalize_uuid
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .snapshot import (
    MAX_VERSION,
    OPERATION_PATCH_FIELDS,
    build_production_operation_snapshot,
    production_operation_target,
)


class ProductionSchedulePrepare:
    """Read full current schedule rows and save a single-category UPDATE proposal."""

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
                # In particular, do not accept an unvalidated assignment_replacement.
                if type(target) is not dict or set(target) != {"production_operation_id", "patch"}:
                    raise ValueError("Invalid schedule-only production input")
                patch = target["patch"]
                if type(patch) is not dict or not patch or not set(patch) <= OPERATION_PATCH_FIELDS:
                    raise ValueError("Invalid production schedule patch")
                values = {}
                for field, value in patch.items():
                    if field == "planned_status":
                        if type(value) is not str or value not in {"PLANNED", "CANCELLED"}:
                            raise ValueError("Invalid planned status")
                        values[field] = value
                    else:
                        values[field] = normalize_timestamp(value)
                normalized.append(
                    {
                        "production_operation_id": normalize_uuid(
                            target["production_operation_id"]
                        ),
                        "patch": values,
                    }
                )
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
            raise ProposalError(
                "INVALID_ARGUMENT", "Invalid production schedule Prepare input"
            ) from error
        ids = [target["production_operation_id"] for target in normalized]
        if len(set(ids)) != len(ids):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Duplicate production operation target")
        replay = self.store.find_by_retry(
            context, retry_key, prepare_input_hash=input_hash, agent_input_hash=agent_input_hash
        )
        if replay is not None:
            return replay
        with self.store._transaction(read_only=True) as connection:
            rows = connection.execute(
                "SELECT production_operation_id,operation_code,process_id,planned_status,"
                "planned_start,planned_end,active,version FROM production_operation "
                "WHERE production_operation_id=ANY(%s::uuid[])",
                (ids,),
            ).fetchall()
        current = {str(row["production_operation_id"]): row for row in rows}
        if len(current) != len(ids):
            raise ProposalError("TARGET_NOT_FOUND", "Production operation target was not found")
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
            patch = target["patch"]
            after = {**row, **patch}
            if after["planned_start"] >= after["planned_end"]:
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Production start must precede end")
            if all(row[field] == value for field, value in patch.items()):
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Production schedule must change")
            try:
                changes.append(production_operation_target(row, patch))
            except ValueError as error:
                raise ProposalError(
                    "INTERNAL_ERROR", "Production current value is invalid"
                ) from error
        snapshot = build_production_operation_snapshot(context, changes, replacement)
        return self.store.save(
            context,
            snapshot,
            retry_key,
            prepare_input_hash=input_hash,
            agent_input_hash=agent_input_hash,
        )
