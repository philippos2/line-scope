"""Internal assignment Execute with atomic parent, interval, history and Outbox updates."""

from psycopg.errors import ForeignKeyViolation, UniqueViolation

from .approvals import ProductionAssignmentApproval
from .assignments import normalize_operation_assignments
from .dependency_cycles import DependencyCycleError, validate_dependency_cycles
from .dependency_prepare import OBSERVE
from .execute import ProductionScheduleExecute, _UpdateExecute
from .graph_locks import acquire_graph_mutation_lock
from .outbox import enqueue_graph_target
from .proposals import ProposalError
from .snapshot import CATEGORIES

ASSIGNMENT = "ProductionOperationEquipmentAssignment"


class ProductionAssignmentExecute(_UpdateExecute):
    """Not routed to HTTP until current-value observation is implemented."""

    def _before_load(self, c, request_id):
        # The immutable saved Target type is a routing hint only. The entire
        # Snapshot is verified under Request/Approval locks after coordination.
        changed = c.execute(
            "SELECT EXISTS(SELECT 1 FROM update_target WHERE update_request_id=%s "
            "AND target_type=%s) AS changed",
            (request_id, ASSIGNMENT),
        ).fetchone()["changed"]
        if changed:
            acquire_graph_mutation_lock(c, shared=False)

    @staticmethod
    def _require_scope(saved):
        ProductionAssignmentApproval._require_scope(
            CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]], saved
        )

    @staticmethod
    def _targets(c, saved):
        targets = saved.snapshot.data["targets"]
        conflict = ProductionAssignmentApproval._conflict_code(c, targets)
        if conflict:
            raise ProposalError(conflict, "Production operation or assignments have changed")
        children = [t for t in targets if t["target_type"] == ASSIGNMENT]
        if not children:
            return targets
        # Preserve Prepare's existence rule. Equipment state/availability is
        # not a constraint on a planned assignment and is not inferred here.
        equipment = sorted({t["after"]["equipment_id"] for t in children if t["after"]["active"]})
        present = c.execute(
            "SELECT equipment_id FROM equipment WHERE equipment_id=ANY(%s::uuid[]) "
            "ORDER BY equipment_id FOR SHARE",
            (equipment,),
        ).fetchall()
        if {str(r["equipment_id"]) for r in present} != set(equipment):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Assignment equipment is unavailable")
        observed = c.execute(OBSERVE).fetchone()
        try:
            final = {
                a["assignment_id"]: normalize_operation_assignments(
                    a["production_operation_id"], [a]
                )[0]
                for a in observed["assignments"]
            }
        except ValueError as error:
            raise ProposalError(
                "INTERNAL_ERROR", "Assignment validation source is invalid"
            ) from error
        final.update({t["target_id"]: t["after"] for t in children})
        groups = {}
        for row in final.values():
            groups.setdefault(row["production_operation_id"], []).append(row)
        try:
            normalized = {
                identifier: normalize_operation_assignments(identifier, rows)
                for identifier, rows in groups.items()
            }
        except ValueError as error:
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Final assignment set violates business rules"
            ) from error
        try:
            validate_dependency_cycles(
                observed["relations"], [r for rows in normalized.values() for r in rows]
            )
        except DependencyCycleError as error:
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Final assignment set violates business rules"
            ) from error
        except ValueError as error:
            raise ProposalError(
                "INTERNAL_ERROR", "Dependency validation source is invalid"
            ) from error
        for parent in targets:
            if (
                parent["target_type"] != "ProductionOperation"
                or "equipment_assignments" not in parent["after"]
            ):
                continue
            active = sorted(
                [r for r in normalized.get(parent["target_id"], []) if r["active"]],
                key=lambda r: r["assignment_id"],
            )
            if active != parent["after"]["equipment_assignments"]:
                raise ProposalError("VERSION_CONFLICT", "Final assignment collection has changed")
        return targets

    @staticmethod
    def _apply(c, request_id, targets, executed_at):
        parents = [t for t in targets if t["target_type"] == "ProductionOperation"]
        ProductionScheduleExecute._apply(c, request_id, parents, executed_at)
        children = [t for t in targets if t["target_type"] == ASSIGNMENT]
        try:
            # Assignment keys are immutable; apply shortening/disabling before
            # insertion and retain each prepared ID, interval and version.
            for target in sorted(children, key=lambda t: t["operation_type"] == "CREATE"):
                after = target["after"]
                if target["operation_type"] == "CREATE":
                    c.execute(
                        "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,"
                        "equipment_id,effective_from,effective_to,active,version,created_at,updated_at) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            after["assignment_id"],
                            after["production_operation_id"],
                            after["equipment_id"],
                            after["effective_from"],
                            after["effective_to"],
                            after["active"],
                            after["version"],
                            executed_at,
                            executed_at,
                        ),
                    )
                else:
                    result = c.execute(
                        "UPDATE production_operation_equipment_assignment SET effective_to=%s,active=%s,version=version+1,updated_at=%s "
                        "WHERE assignment_id=%s AND version=%s",
                        (
                            after["effective_to"],
                            after["active"],
                            executed_at,
                            target["target_id"],
                            target["expected_version"],
                        ),
                    )
                    if result.rowcount != 1:
                        raise ProposalError("VERSION_CONFLICT", "Assignment version has changed")
        except UniqueViolation as error:
            raise ProposalError(
                "CREATE_CONFLICT", "Assignment identity or business key exists"
            ) from error
        except ForeignKeyViolation as error:
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION", "Assignment reference is unavailable"
            ) from error

    def _after_history(self, c, request_id, targets):
        for target in targets:
            if target["target_type"] == ASSIGNMENT:
                enqueue_graph_target(c, request_id, target)
