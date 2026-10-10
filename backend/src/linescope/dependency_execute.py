"""Internal dependency Execute: SoR, history and Outbox commit atomically."""

from psycopg import sql
from psycopg.errors import UniqueViolation

from .approvals import DependencyApproval
from .core_dependencies import (
    insert_dependency_relation,
    lock_dependency_endpoint,
    update_dependency_relation,
)
from .dependency_cycles import DependencyCycleError, validate_dependency_cycles
from .dependency_prepare import OBSERVE
from .execute import _UpdateExecute
from .graph_locks import acquire_graph_mutation_lock
from .outbox import enqueue_graph_target
from .proposals import ProposalError
from .relations import RelationSetConflict, normalize_relation_set
from .snapshot import CATEGORIES


class DependencyExecute(_UpdateExecute):
    """Dependency updates used by the human action API."""

    def _before_load(self, c, request_id):
        acquire_graph_mutation_lock(c, shared=False)

    @staticmethod
    def _require_scope(saved):
        DependencyApproval._require_scope(
            CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]], saved
        )

    @staticmethod
    def _targets(c, saved):
        targets = saved.snapshot.data["targets"]
        conflict = DependencyApproval._conflict_code(c, targets)
        if conflict:
            raise ProposalError(conflict, "Dependency relation has changed")
        endpoints = {
            (t["after"][f"{side}_entity_type"], t["after"][f"{side}_entity_id"])
            for t in targets
            for side in ("source", "target")
        }
        # Endpoint rows remain active and present until commit. Graph writers
        # coordinate through the exclusive mutation lock before business locks.
        for kind, identifier in sorted(endpoints):
            row = lock_dependency_endpoint(c, kind, identifier)
            if row is None or not row["active"]:
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Dependency endpoint is unavailable")
        observed = c.execute(OBSERVE).fetchone()
        final = {r["dependency_relation_id"]: r for r in observed["relations"]}
        final.update({t["target_id"]: t["after"] for t in targets})
        try:
            rows = normalize_relation_set(list(final.values()))
            validate_dependency_cycles(rows, observed["assignments"])
        except (RelationSetConflict, DependencyCycleError) as error:
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Final dependency set violates business rules"
            ) from error
        except ValueError as error:
            raise ProposalError(
                "INTERNAL_ERROR", "Dependency validation source is invalid"
            ) from error
        return targets

    @staticmethod
    def _apply(c, request_id, targets, executed_at):
        # Defer only this table's business-key constraint. Final-set validation
        # already permits keys moved by another Target in the same request.
        constraints = c.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='dependency_relation'::regclass "
            "AND contype='u' AND condeferrable ORDER BY conname"
        ).fetchall()
        try:
            for constraint in constraints:
                c.execute(
                    sql.SQL("SET CONSTRAINTS {} DEFERRED").format(
                        sql.Identifier(constraint["conname"])
                    )
                )
            # Apply UPDATE/DISABLE before CREATE; no intermediate state commits.
            for target in sorted(targets, key=lambda t: t["operation_type"] == "CREATE"):
                after = target["after"]
                if target["operation_type"] == "CREATE":
                    insert_dependency_relation(c, after, executed_at)
                else:
                    result = update_dependency_relation(c, target, executed_at)
                    if result.rowcount != 1:
                        raise ProposalError("VERSION_CONFLICT", "Dependency version has changed")
            for constraint in constraints:
                c.execute(
                    sql.SQL("SET CONSTRAINTS {} IMMEDIATE").format(
                        sql.Identifier(constraint["conname"])
                    )
                )
        except UniqueViolation as error:
            raise ProposalError(
                "CREATE_CONFLICT", "Dependency identity or business key exists"
            ) from error

    def _after_history(self, c, request_id, targets):
        for target in targets:
            enqueue_graph_target(c, request_id, target)

    def observe_current(self, result):
        """Observe current PG values separately from the durable execution result."""
        targets = result["targets"]
        ids = [t["target_id"] for t in targets]
        with self.store._transaction(read_only=True) as c:
            row = c.execute(
                "SELECT statement_timestamp() AS observed_at,"
                "(SELECT jsonb_agg(to_jsonb(r)-'created_at'-'updated_at') "
                "FROM dependency_relation r WHERE dependency_relation_id=ANY(%s::uuid[])) AS relations",
                (ids,),
            ).fetchone()
        if len(row["relations"] or []) != len(targets):
            raise ProposalError("TARGET_NOT_FOUND", "A current dependency target is unavailable")
        try:
            rows = normalize_relation_set(row["relations"])
        except ValueError as error:
            raise ProposalError("INTERNAL_ERROR", "Current dependency state is invalid") from error
        confirmed = {t["target_id"]: t["after"]["version"] for t in targets}
        return {
            "current_snapshot": {
                "targets": [
                    {
                        "target_type": "DependencyRelation",
                        "target_id": r["dependency_relation_id"],
                        "snapshot": r,
                    }
                    for r in rows
                ]
            },
            "current_versions": [
                {
                    "target_type": "DependencyRelation",
                    "target_id": r["dependency_relation_id"],
                    "version": r["version"],
                    "confirmed_version": confirmed[r["dependency_relation_id"]],
                    "version_delta": r["version"] - confirmed[r["dependency_relation_id"]],
                }
                for r in rows
            ],
            "observed_at": row["observed_at"],
        }
