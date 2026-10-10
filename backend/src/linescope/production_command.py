"""Server-bound schedule-only Prepare from explicit original-message values."""

from .agent_input import AgentInput
from .agent_tools import AgentToolSession
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .reads import ToolError
from .tools import ToolDispatcher
from .update_intent import production_schedule_command


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
        command = production_schedule_command(request)
        if command is None or request.context_id or request.explicit_as_of:
            raise ToolError(
                "INVALID_ARGUMENT", "A new explicit production schedule command is required"
            )
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
                row = c.execute(
                    "SELECT production_operation_id FROM production_operation WHERE operation_code=%s",
                    (command.operation_code,),
                ).fetchone()
        except ProposalError as error:
            raise ToolError(error.code, error.message) from error
        if row is None:
            raise ToolError("TARGET_NOT_FOUND", "Requested production operation code was not found")
        session = AgentToolSession(
            context, request, self.dispatcher, prepare_authorized=True, event_logger=self.events
        )
        return session.run(
            "prepare_production_operation_update",
            {
                "production_operation_id": str(row["production_operation_id"]),
                "patch": command.patch,
            },
        )
