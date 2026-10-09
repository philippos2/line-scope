"""Internal equipment-state Prepare; no HTTP/Tool or Approval/Execute entrypoint."""

import re

from .canonical import canonical_hash, normalize_uuid
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .snapshot import STATE_CODES, build_equipment_state_snapshot, equipment_state_target


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
