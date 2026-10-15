"""Formal economic input workflow, sharing common proposal/approval/execution controls."""

from psycopg.errors import ForeignKeyViolation, UniqueViolation

from ..domain.canonical import canonical_hash, normalize_uuid
from ..domain.economics import calculate, economic_target, normalize_input, normalize_record
from ..domain.snapshot import build_economic_input_snapshot
from ..execution import ExecutionContext
from ..persistence import core_economics as queries
from ..persistence.database import Database
from .execute import _UpdateExecute
from .proposals import ProposalError, ProposalStore


def require(context, *, write=False):
    if not isinstance(context, ExecutionContext):
        raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
    if context.role not in ({"manager"} if write else {"maintenance", "production", "manager"}):
        raise ProposalError("AUTHORIZATION_DENIED", "Economic input permission is required")


class EconomicInputs:
    def __init__(self, database):
        self.store = ProposalStore(database)
        self.read_store = ProposalStore(
            database.for_reads() if isinstance(database, Database) else database
        )

    def prepare(self, context, values):
        require(context, write=True)
        try:
            if type(values) is not dict or set(values) != {
                "retry_key",
                "economic_input_id",
                "input",
                "supersedes_update_request_id",
            }:
                raise ValueError("Invalid economic Prepare fields")
            normalized = normalize_input(values["input"])
            identifier = (
                normalize_uuid(values["economic_input_id"])
                if values["economic_input_id"] is not None
                else None
            )
            replacement = (
                normalize_uuid(values["supersedes_update_request_id"])
                if values["supersedes_update_request_id"] is not None
                else None
            )
            retry_key = normalize_uuid(values["retry_key"])
        except (ValueError, TypeError) as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid economic Prepare input") from error
        input_hash = canonical_hash(
            {
                "economic_input_id": identifier,
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
            current = queries.read(connection, identifier) if identifier else None
        if identifier and current is None:
            raise ProposalError("TARGET_NOT_FOUND", "Economic input was not found")
        try:
            target = economic_target(normalized, current)
            snapshot = build_economic_input_snapshot(context, [target], replacement)
        except ValueError as error:
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Economic input must change only its payload"
            ) from error
        saved = self.store.save(
            context, snapshot, retry_key, prepare_input_hash=input_hash, agent_input_hash=input_hash
        )
        return self.store.get(context, str(saved.update_request_id))

    def get(self, context, identifier):
        require(context)
        try:
            identifier = normalize_uuid(identifier)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid economic input ID") from error
        with self.read_store._transaction(read_only=True) as connection:
            row = queries.read(connection, identifier)
            if row is None:
                raise ProposalError("TARGET_NOT_FOUND", "Economic input was not found")
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


class EconomicApproval:
    @staticmethod
    def _require_scope(category, saved):
        if category != "ECONOMIC_INPUT" or any(
            target["target_type"] != "EconomicInput"
            or target["operation_type"] not in {"CREATE", "UPDATE"}
            for target in saved.snapshot.data["targets"]
        ):
            raise ProposalError("INVALID_ARGUMENT", "Economic input targets required")

    @staticmethod
    def _conflict_code(connection, targets):
        # Common request/approval locks are held. Stable FK first, then all input rows.
        for identifier in sorted({target["after"]["equipment_id"] for target in targets}):
            if not queries.equipment(connection, identifier, lock=True):
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


class EconomicExecute(_UpdateExecute):
    @staticmethod
    def _require_scope(saved):
        EconomicApproval._require_scope("ECONOMIC_INPUT", saved)

    @staticmethod
    def _targets(connection, saved):
        targets = saved.snapshot.data["targets"]
        conflict = EconomicApproval._conflict_code(connection, targets)
        if conflict:
            raise ProposalError(conflict, "Prepared economic input has changed")
        return targets

    @staticmethod
    def _apply(connection, request_id, targets, executed_at):
        for target in sorted(targets, key=lambda target: target["after"]["input_code"]):
            try:
                if queries.write(connection, target) != 1:
                    raise ProposalError("INTERNAL_ERROR", "Economic input was not written")
            except UniqueViolation as error:
                raise ProposalError("CREATE_CONFLICT", "Economic input already exists") from error
            except ForeignKeyViolation as error:
                raise ProposalError(
                    "BUSINESS_RULE_VIOLATION", "Economic equipment reference is invalid"
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
                    raise ProposalError("TARGET_NOT_FOUND", "Current economic input is unavailable")
                value = normalize_record(dict(row))
                identity = {"target_type": "EconomicInput", "target_id": target["target_id"]}
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
