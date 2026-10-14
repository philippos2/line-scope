"""Server-bound schedule or assignment Prepare from explicit original values."""

from ..agent.agent_input import AgentInput
from ..agent.agent_tools import AgentToolSession
from ..agent.update_intent import production_assignment_command, production_schedule_command
from ..execution import ExecutionContext
from ..persistence.core_reads import get_operation_by_code
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .reads import ToolError
from .tools import ToolDispatcher


class ProductionCommandPrepare:
    def __init__(self, database, *, event_logger=None):
        self.store = ProposalStore(database)
        self.dispatcher = ToolDispatcher(database)
        self.events = event_logger

    def run(self, context, request):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if not isinstance(request, AgentInput):
            raise ToolError("INVALID_ARGUMENT", "Validated original Agent input is required")
        assignment = production_assignment_command(request)
        command = assignment or production_schedule_command(request)
        if command is None or request.context_id or request.explicit_as_of:
            raise ToolError("INVALID_ARGUMENT", "A new explicit production command is required")
        if context.role not in REQUEST_ROLES["PRODUCTION_OPERATION"]:
            raise ToolError("AUTHORIZATION_DENIED", "Production request permission is required")
        try:
            # Saved retry identity wins over mutable business-code resolution.
            saved = self.store.find_by_retry(
                context, request.retry_key, agent_input_hash=request.input_hash
            )
            if saved is not None:
                return saved
            # Private application resolution, not a new LLM Tool or arbitrary SQL.
            # operation_code is an exact, unique business key in PostgreSQL.
            with self.store._transaction(read_only=True) as c:
                row = get_operation_by_code(c, command.operation_code)
        except ProposalError as error:
            raise ToolError(error.code, error.message) from error
        if row is None:
            raise ToolError("TARGET_NOT_FOUND", "Requested production operation code was not found")
        session = AgentToolSession(
            context, request, self.dispatcher, prepare_authorized=True, event_logger=self.events
        )
        values = {"production_operation_id": str(row["production_operation_id"])}
        if assignment is None:
            values["patch"] = command.patch
        else:
            if len(set(assignment.equipment_codes)) != len(assignment.equipment_codes):
                raise ToolError("INVALID_ARGUMENT", "Duplicate equipment code")
            equipment_ids = []
            for code in assignment.equipment_codes:
                result = session.run(
                    "search_equipment", {"filter": {"equipment_code": code}, "page_size": 2}
                )
                items = result.data["items"]
                if not items:
                    raise ToolError("TARGET_NOT_FOUND", "Requested equipment code was not found")
                if len(items) != 1 or result.data["next_cursor"] is not None:
                    raise ToolError("TARGET_AMBIGUOUS", "Equipment must be uniquely resolved")
                equipment_ids.append(items[0]["equipment_id"])
            values["assignment_replacement"] = {
                "effective_from": assignment.effective_from,
                "effective_to": assignment.effective_to,
                "equipment_ids": equipment_ids,
            }
        return session.run("prepare_production_operation_update", values)
