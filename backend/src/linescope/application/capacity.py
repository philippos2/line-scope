"""Formal capacity input workflow, sharing common proposal/approval/execution controls."""

from psycopg.errors import ForeignKeyViolation, UniqueViolation

from ..domain.canonical import canonical_hash, normalize_uuid
from ..domain.capacity import calculate, capacity_target, normalize_input, normalize_record
from ..domain.snapshot import build_capacity_input_snapshot
from ..execution import ExecutionContext
from ..pagination import CursorCodec
from ..persistence import core_capacity as queries
from ..persistence.database import Database
from .execute import _UpdateExecute
from .proposals import ProposalError, ProposalStore


def require(context, *, write=False):
    if not isinstance(context, ExecutionContext):
        raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
    if context.role not in ({"manager"} if write else {"maintenance", "production", "manager"}):
        raise ProposalError("AUTHORIZATION_DENIED", "Capacity input permission is required")


class CapacityInputs:
    def __init__(self, database):
        self.cursors = CursorCodec()
        self.store = ProposalStore(database)
        self.read_store = ProposalStore(
            database.for_reads() if isinstance(database, Database) else database
        )

    def prepare(self, context, values):
        require(context, write=True)
        try:
            if type(values) is not dict or set(values) != {
                "retry_key",
                "capacity_input_id",
                "input",
                "supersedes_update_request_id",
            }:
                raise ValueError("Invalid capacity Prepare fields")
            normalized = normalize_input(values["input"])
            identifier = (
                normalize_uuid(values["capacity_input_id"])
                if values["capacity_input_id"] is not None
                else None
            )
            replacement = (
                normalize_uuid(values["supersedes_update_request_id"])
                if values["supersedes_update_request_id"] is not None
                else None
            )
            retry_key = normalize_uuid(values["retry_key"])
        except (ValueError, TypeError) as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid capacity Prepare input") from error
        input_hash = canonical_hash(
            {
                "capacity_input_id": identifier,
                "input": normalized,
                "supersedes_update_request_id": replacement,
            }
        )
        # Direct explicit HTTP input is the original intent; no LLM-supplied authority/hash.
        saved = self.store.find_by_retry(
            context, retry_key, prepare_input_hash=input_hash, agent_input_hash=input_hash
        )
        if saved is not None:
            return self.store.get(context, str(saved.update_request_id))
        with self.read_store._transaction(read_only=True) as connection:
            if not queries.equipment(connection, normalized["equipment_id"]):
                raise ProposalError("TARGET_NOT_FOUND", "Equipment was not found")
            if not queries.product(connection, normalized["product_id"]):
                raise ProposalError("TARGET_NOT_FOUND", "Product was not found")
            current = queries.read(connection, identifier) if identifier else None
        if identifier and current is None:
            raise ProposalError("TARGET_NOT_FOUND", "Capacity input was not found")
        try:
            target = capacity_target(normalized, current)
            snapshot = build_capacity_input_snapshot(context, [target], replacement)
        except ValueError as error:
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Capacity input must change only its payload"
            ) from error
        saved = self.store.save(
            context, snapshot, retry_key, prepare_input_hash=input_hash, agent_input_hash=input_hash
        )
        return self.store.get(context, str(saved.update_request_id))

    def search(self, context, arguments):
        require(context)
        try:
            if type(arguments) is not dict or not set(arguments) <= {
                "filter",
                "page_size",
                "cursor",
            }:
                raise ValueError("Invalid search fields")
            filters = arguments.get("filter", {})
            if type(filters) is not dict or not set(filters) <= {
                "equipment_id",
                "input_code",
                "equipment_query",
            }:
                raise ValueError("Invalid search filter")
            normalized = {}
            for key, value in filters.items():
                if key == "equipment_id":
                    normalized[key] = normalize_uuid(value)
                elif type(value) is str and value.strip() and len(value) <= 100:
                    normalized[key] = value
                else:
                    raise ValueError("Invalid search text")
            size = arguments.get("page_size", 20)
            if type(size) is not int or not 1 <= size <= 100:
                raise ValueError("Invalid page size")
            binding = self.cursors.binding(context, "search_capacity_inputs", normalized)
            cursor = arguments.get("cursor")
            after = self.cursors.decode(cursor, binding) if cursor is not None else None
        except (ValueError, TypeError) as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid capacity input search") from error
        with self.read_store._transaction(read_only=True) as connection:
            rows = queries.search(connection, normalized, size, after)
            observed_at = (
                rows[0]["_observed_at"]
                if rows
                else connection.execute("SELECT statement_timestamp() AS at").fetchone()["at"]
            )
        items = [
            {key: value for key, value in row.items() if key != "_observed_at"}
            for row in rows[:size]
        ]
        return {
            "items": items,
            "next_cursor": self.cursors.encode(binding, items[-1]["capacity_input_id"])
            if len(rows) > size
            else None,
            "observed_at": observed_at,
            "source": "REGISTERED_INPUT",
        }

    def get(self, context, identifier):
        require(context)
        try:
            identifier = normalize_uuid(identifier)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid capacity input ID") from error
        with self.read_store._transaction(read_only=True) as connection:
            row = queries.read(connection, identifier)
            if row is None:
                raise ProposalError("TARGET_NOT_FOUND", "Capacity input was not found")
            observed_at = connection.execute("SELECT transaction_timestamp() AS at").fetchone()[
                "at"
            ]
        record = normalize_record(dict(row))
        return {
            "input": record,
            "calculation": calculate(record["payload"]),
            "source": "REGISTERED_INPUT",
            "observed_at": observed_at,
        }


class CapacityApproval:
    @staticmethod
    def _require_scope(category, saved):
        if category != "CAPACITY_INPUT" or any(
            target["target_type"] != "CapacityInput"
            or target["operation_type"] not in {"CREATE", "UPDATE"}
            for target in saved.snapshot.data["targets"]
        ):
            raise ProposalError("INVALID_ARGUMENT", "Capacity input targets required")

    @staticmethod
    def _conflict_code(connection, targets):
        # Common request/approval locks are held. Stable FK first, then all input rows.
        for identifier in sorted({target["after"]["equipment_id"] for target in targets}):
            if not queries.equipment(connection, identifier, lock=True):
                return "BUSINESS_RULE_VIOLATION"
        for identifier in sorted({target["after"]["product_id"] for target in targets}):
            if not queries.product(connection, identifier, lock=True):
                return "BUSINESS_RULE_VIOLATION"
        for target in sorted(targets, key=lambda target: target["target_id"]):
            if target["operation_type"] == "CREATE":
                if queries.conflict(connection, target["after"]):
                    return "CREATE_CONFLICT"
            else:
                row = queries.read(connection, target["target_id"], lock=True)
                if row is None or normalize_record(dict(row)) != target["before"]:
                    return "VERSION_CONFLICT"
        return None


class CapacityExecute(_UpdateExecute):
    @staticmethod
    def _require_scope(saved):
        CapacityApproval._require_scope("CAPACITY_INPUT", saved)

    @staticmethod
    def _targets(connection, saved):
        targets = saved.snapshot.data["targets"]
        conflict = CapacityApproval._conflict_code(connection, targets)
        if conflict:
            raise ProposalError(conflict, "Prepared capacity input has changed")
        return targets

    @staticmethod
    def _apply(connection, request_id, targets, executed_at):
        for target in sorted(targets, key=lambda target: target["after"]["input_code"]):
            try:
                if queries.write(connection, target) != 1:
                    raise ProposalError("INTERNAL_ERROR", "Capacity input was not written")
            except UniqueViolation as error:
                raise ProposalError("CREATE_CONFLICT", "Capacity input already exists") from error
            except ForeignKeyViolation as error:
                raise ProposalError(
                    "BUSINESS_RULE_VIOLATION", "Capacity equipment reference is invalid"
                ) from error

    def observe_current(self, result):
        snapshots, versions = [], []
        with self.store._transaction(read_only=True) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            observed_at = connection.execute("SELECT transaction_timestamp() AS at").fetchone()[
                "at"
            ]
            for target in result["targets"]:
                row = queries.read(connection, target["target_id"])
                if row is None:
                    raise ProposalError("TARGET_NOT_FOUND", "Current capacity input is unavailable")
                value = normalize_record(dict(row))
                identity = {"target_type": "CapacityInput", "target_id": target["target_id"]}
                snapshots.append({**identity, "snapshot": value})
                confirmed = target["after"]["version"]
                versions.append(
                    {
                        **identity,
                        "version": value["version"],
                        "confirmed_version": confirmed,
                        "version_delta": value["version"] - confirmed,
                    }
                )
        return {
            "current_snapshot": {"targets": snapshots},
            "current_versions": versions,
            "observed_at": observed_at,
        }
