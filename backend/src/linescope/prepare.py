"""Internal update Prepare services; no HTTP/Tool or Approval/Execute entrypoint."""

import re

from .canonical import canonical_hash, normalize_timestamp, normalize_uuid
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .snapshot import (
    MAX_VERSION,
    PLAN_PATCH_FIELDS,
    STATE_CODES,
    build_equipment_state_snapshot,
    build_maintenance_plan_snapshot,
    build_maintenance_snapshot,
    equipment_state_target,
    maintenance_plan_create_target,
    maintenance_plan_target,
    maintenance_record_create_target,
)


class EquipmentStatePrepare:
    def __init__(self, database):
        self.store = ProposalStore(database)

    def prepare(
        self, context, targets, retry_key, *, agent_input_hash, supersedes_update_request_id=None
    ):
        """Accept resolved IDs and explicit values, never caller-supplied versions.

        All current rows come from one statement snapshot without business row
        locks. Approval/Execute must subsequently revalidate their versions.
        The orchestrator supplies the immutable Agent input hash and retry key.
        """
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if context.role not in REQUEST_ROLES["EQUIPMENT_STATE"]:
            raise ProposalError(
                "AUTHORIZATION_DENIED", "Equipment state request permission is required"
            )
        try:
            if type(agent_input_hash) is not str or not re.fullmatch(
                r"[0-9a-f]{64}", agent_input_hash
            ):
                raise ValueError("A normalized Agent input hash is required")
            if type(targets) is not list or not targets:
                raise ValueError("Targets must be a nonempty array")
            normalized = []
            for target in targets:
                if type(target) is not dict or set(target) != {"equipment_id", "state_code"}:
                    raise ValueError("Invalid equipment state input")
                state = target["state_code"]
                if type(state) is not str or state not in STATE_CODES:
                    raise ValueError("Invalid state")
                normalized.append(
                    {"equipment_id": normalize_uuid(target["equipment_id"]), "state_code": state}
                )
            replacement = (
                normalize_uuid(supersedes_update_request_id)
                if supersedes_update_request_id is not None
                else None
            )
        except ValueError as error:
            raise ProposalError(
                "INVALID_ARGUMENT", "Invalid equipment state Prepare input"
            ) from error
        ids = [target["equipment_id"] for target in normalized]
        if len(set(ids)) != len(ids):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Duplicate equipment target")
        # Targets are a set; equivalent UUID spelling and order share a hash.
        normalized.sort(key=lambda target: target["equipment_id"])
        input_hash = canonical_hash(
            {
                "prepare_tool": "prepare_equipment_state_update",
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
            rows = connection.execute(
                "SELECT e.equipment_id,s.state_code,s.version FROM equipment e "
                "LEFT JOIN equipment_current_state s USING(equipment_id) "
                "WHERE e.equipment_id=ANY(%s::uuid[])",
                (ids,),
            ).fetchall()
        current = {str(row["equipment_id"]): row for row in rows}
        if len(current) != len(ids):
            raise ProposalError("TARGET_NOT_FOUND", "Equipment target was not found")
        changes = []
        for target in normalized:
            row = current[target["equipment_id"]]
            if row["state_code"] is None or row["version"] is None:
                raise ProposalError("INTERNAL_ERROR", "Equipment current state is missing")
            if row["state_code"] == target["state_code"]:
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Equipment state must change")
            try:
                changes.append(equipment_state_target(row, target["state_code"]))
            except ValueError as error:
                raise ProposalError(
                    "INTERNAL_ERROR", "Equipment current state is invalid"
                ) from error
        snapshot = build_equipment_state_snapshot(context, changes, replacement)
        return self.store.save(
            context,
            snapshot,
            retry_key,
            prepare_input_hash=input_hash,
            agent_input_hash=agent_input_hash,
        )


class MaintenancePlanPrepare:
    """Prepare only existing maintenance-plan UPDATE targets."""

    def __init__(self, database):
        self.store = ProposalStore(database)

    def prepare(
        self, context, targets, retry_key, *, agent_input_hash, supersedes_update_request_id=None
    ):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if context.role not in REQUEST_ROLES["MAINTENANCE"]:
            raise ProposalError(
                "AUTHORIZATION_DENIED", "Maintenance request permission is required"
            )
        try:
            if type(agent_input_hash) is not str or not re.fullmatch(
                r"[0-9a-f]{64}", agent_input_hash
            ):
                raise ValueError("A normalized Agent input hash is required")
            if type(targets) is not list or not targets:
                raise ValueError("Targets must be a nonempty array")
            normalized = []
            for target in targets:
                if type(target) is not dict or set(target) != {"maintenance_plan_id", "patch"}:
                    raise ValueError("Invalid maintenance plan input")
                patch = target["patch"]
                if type(patch) is not dict or not patch or not set(patch) <= PLAN_PATCH_FIELDS:
                    raise ValueError("Invalid maintenance plan patch")
                values = {}
                for field, value in patch.items():
                    if field == "plan_status":
                        if type(value) is not str or value not in {"PLANNED", "CANCELLED"}:
                            raise ValueError("Invalid maintenance plan status")
                        values[field] = value
                    else:
                        values[field] = normalize_timestamp(value)
                normalized.append(
                    {
                        "maintenance_plan_id": normalize_uuid(target["maintenance_plan_id"]),
                        "patch": values,
                    }
                )
            replacement = (
                normalize_uuid(supersedes_update_request_id)
                if supersedes_update_request_id is not None
                else None
            )
        except ValueError as error:
            raise ProposalError(
                "INVALID_ARGUMENT", "Invalid maintenance plan Prepare input"
            ) from error
        ids = [target["maintenance_plan_id"] for target in normalized]
        if len(set(ids)) != len(ids):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Duplicate maintenance plan target")
        normalized.sort(key=lambda target: target["maintenance_plan_id"])
        input_hash = canonical_hash(
            {
                "prepare_tool": "prepare_maintenance_plan_update",
                "targets": normalized,
                "supersedes_update_request_id": replacement,
            }
        )
        replay = self.store.find_by_retry(
            context, retry_key, prepare_input_hash=input_hash, agent_input_hash=agent_input_hash
        )
        if replay is not None:
            return replay
        # Every target and its full business values share one statement snapshot.
        with self.store._transaction(read_only=True) as connection:
            rows = connection.execute(
                "SELECT maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,"
                "plan_status,version FROM maintenance_plan WHERE maintenance_plan_id=ANY(%s::uuid[])",
                (ids,),
            ).fetchall()
        current = {str(row["maintenance_plan_id"]): row for row in rows}
        if len(current) != len(ids):
            raise ProposalError("TARGET_NOT_FOUND", "Maintenance plan target was not found")
        changes = []
        for target in normalized:
            row = dict(current[target["maintenance_plan_id"]])
            try:
                row["planned_start"] = normalize_timestamp(row["planned_start"])
                row["planned_end"] = normalize_timestamp(row["planned_end"])
                if not 1 <= row["version"] < MAX_VERSION:
                    raise ValueError("Current version cannot be incremented")
            except ValueError as error:
                raise ProposalError(
                    "INTERNAL_ERROR", "Maintenance plan current value is invalid"
                ) from error
            patch = target["patch"]
            after = {**row, **patch}
            if after["planned_start"] >= after["planned_end"]:
                raise ProposalError(
                    "BUSINESS_RULE_VIOLATION", "Maintenance plan start must precede end"
                )
            if all(row[field] == value for field, value in patch.items()):
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Maintenance plan must change")
            try:
                changes.append(maintenance_plan_target(row, patch))
            except ValueError as error:
                raise ProposalError(
                    "INTERNAL_ERROR", "Maintenance plan current value is invalid"
                ) from error
        snapshot = build_maintenance_plan_snapshot(context, changes, replacement)
        return self.store.save(
            context,
            snapshot,
            retry_key,
            prepare_input_hash=input_hash,
            agent_input_hash=agent_input_hash,
        )


PLAN_CREATE = "prepare_maintenance_plan_create"
RECORD_CREATE = "prepare_maintenance_record_create"
CREATE_FACTORIES = {
    PLAN_CREATE: maintenance_plan_create_target,
    RECORD_CREATE: maintenance_record_create_target,
}


def _maintenance_create_input(tool, values):
    if tool not in CREATE_FACTORIES or type(values) is not dict:
        raise ValueError("Unsupported maintenance CREATE input")
    if tool == PLAN_CREATE:
        fields = {"plan_code", "equipment_id", "planned_start", "planned_end", "plan_status"}
        if set(values) != fields or type(values["plan_code"]) is not str:
            raise ValueError("Invalid maintenance plan input")
        if type(values["plan_status"]) is not str or values["plan_status"] not in {
            "PLANNED",
            "CANCELLED",
        }:
            raise ValueError("Invalid plan status")
        return {
            **values,
            "equipment_id": normalize_uuid(values["equipment_id"]),
            "planned_start": normalize_timestamp(values["planned_start"]),
            "planned_end": normalize_timestamp(values["planned_end"]),
        }
    fields = {"record_code", "equipment_id", "performed_at", "result"}
    if not fields <= set(values) or not set(values) <= fields | {"maintenance_plan_id"}:
        raise ValueError("Invalid maintenance record fields")
    if (
        type(values["record_code"]) is not str
        or type(values["result"]) is not str
        or not values["result"].strip()
    ):
        raise ValueError("Invalid maintenance record text")
    plan_id = values.get("maintenance_plan_id")
    return {
        **values,
        "equipment_id": normalize_uuid(values["equipment_id"]),
        "performed_at": normalize_timestamp(values["performed_at"]),
        "maintenance_plan_id": normalize_uuid(plan_id) if plan_id is not None else None,
    }


class MaintenanceCreatePrepare:
    """Prepare plan/record CREATEs; linked plans must already exist in the SoR."""

    def __init__(self, database):
        self.store = ProposalStore(database)

    def prepare(
        self, context, targets, retry_key, *, agent_input_hash, supersedes_update_request_id=None
    ):
        if not isinstance(context, ExecutionContext):
            raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if context.role not in REQUEST_ROLES["MAINTENANCE"]:
            raise ProposalError(
                "AUTHORIZATION_DENIED", "Maintenance request permission is required"
            )
        try:
            if type(agent_input_hash) is not str or not re.fullmatch(
                r"[0-9a-f]{64}", agent_input_hash
            ):
                raise ValueError("A normalized Agent input hash is required")
            if type(targets) is not list or not targets:
                raise ValueError("Targets must be a nonempty array")
            normalized = []
            for target in targets:
                if type(target) is not dict or set(target) != {"prepare_tool", "input"}:
                    raise ValueError("Invalid CREATE target fields")
                tool = target["prepare_tool"]
                if type(tool) is not str:
                    raise ValueError("Invalid Prepare Tool name")
                if tool in {
                    "prepare_equipment_state_update",
                    "prepare_production_operation_update",
                    "prepare_dependency_relation_update",
                }:
                    raise ProposalError(
                        "BUSINESS_RULE_VIOLATION", "A request must use one business category"
                    )
                normalized.append(
                    {
                        "prepare_tool": tool,
                        "input": _maintenance_create_input(tool, target["input"]),
                    }
                )
            replacement = (
                normalize_uuid(supersedes_update_request_id)
                if supersedes_update_request_id is not None
                else None
            )
            normalized.sort(
                key=lambda target: (
                    target["prepare_tool"],
                    target["input"].get("plan_code", target["input"].get("record_code")),
                )
            )
            input_hash = canonical_hash(
                {
                    "targets": normalized,
                    "supersedes_update_request_id": replacement,
                }
            )
        except ValueError as error:
            raise ProposalError(
                "INVALID_ARGUMENT", "Invalid maintenance CREATE Prepare input"
            ) from error
        keys = [
            (
                target["prepare_tool"],
                target["input"].get("plan_code", target["input"].get("record_code")),
            )
            for target in normalized
        ]
        if len(set(keys)) != len(keys):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Duplicate CREATE business key")
        replay = self.store.find_by_retry(
            context, retry_key, prepare_input_hash=input_hash, agent_input_hash=agent_input_hash
        )
        if replay is not None:
            return replay
        for target in normalized:
            values = target["input"]
            if (
                target["prepare_tool"] == PLAN_CREATE
                and values["planned_start"] >= values["planned_end"]
            ):
                raise ProposalError(
                    "BUSINESS_RULE_VIOLATION", "Maintenance plan start must precede end"
                )
        equipment_ids = sorted({target["input"]["equipment_id"] for target in normalized})
        plan_ids = sorted(
            {
                target["input"]["maintenance_plan_id"]
                for target in normalized
                if target["prepare_tool"] == RECORD_CREATE
                and target["input"]["maintenance_plan_id"] is not None
            }
        )
        plan_codes = [
            target["input"]["plan_code"]
            for target in normalized
            if target["prepare_tool"] == PLAN_CREATE
        ]
        record_codes = [
            target["input"]["record_code"]
            for target in normalized
            if target["prepare_tool"] == RECORD_CREATE
        ]
        # References and business-key conflicts share one PostgreSQL statement snapshot.
        with self.store._transaction(read_only=True) as connection:
            facts = connection.execute(
                "SELECT ARRAY(SELECT equipment_id::text FROM equipment WHERE equipment_id=ANY(%s::uuid[])) AS equipment_ids,"
                "COALESCE((SELECT jsonb_object_agg(maintenance_plan_id::text,equipment_id::text) "
                "FROM maintenance_plan WHERE maintenance_plan_id=ANY(%s::uuid[])),'{}'::jsonb) AS plans,"
                "ARRAY(SELECT plan_code FROM maintenance_plan WHERE plan_code=ANY(%s::text[])) AS plan_conflicts,"
                "ARRAY(SELECT record_code FROM maintenance_record WHERE record_code=ANY(%s::text[])) AS record_conflicts",
                (equipment_ids, plan_ids, plan_codes, record_codes),
            ).fetchone()
        if set(facts["equipment_ids"]) != set(equipment_ids) or set(facts["plans"]) != set(
            plan_ids
        ):
            raise ProposalError("TARGET_NOT_FOUND", "Maintenance reference was not found")
        for target in normalized:
            values = target["input"]
            plan_id = values.get("maintenance_plan_id")
            if plan_id is not None and facts["plans"][plan_id] != values["equipment_id"]:
                raise ProposalError(
                    "BUSINESS_RULE_VIOLATION", "Maintenance plan equipment does not match"
                )
        if facts["plan_conflicts"] or facts["record_conflicts"]:
            raise ProposalError("CREATE_CONFLICT", "Maintenance business key already exists")
        # IDs are generated only for a new validated proposal and never hashed as input.
        changes = [
            CREATE_FACTORIES[target["prepare_tool"]](target["input"]) for target in normalized
        ]
        snapshot = build_maintenance_snapshot(context, changes, replacement)
        return self.store.save(
            context,
            snapshot,
            retry_key,
            prepare_input_hash=input_hash,
            agent_input_hash=agent_input_hash,
        )
