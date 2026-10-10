"""Server-bound, single-plan UPDATE Prepare from explicit original-message values.

No LLM-supplied IDs, values or versions are accepted. Unsupported language and
continuation contexts require the future clarification orchestrator.
"""

from .agent_input import AgentInput
from .agent_tools import AgentToolSession
from .execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .reads import ToolError
from .tools import ToolDispatcher
from .update_intent import maintenance_plan_command


class MaintenanceCommandPrepare:
    def __init__(self, database, *, event_logger=None):
        self.store = ProposalStore(database)
        self.dispatcher = ToolDispatcher(database)
        self.events = event_logger

    def run(self, context, request):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if not isinstance(request, AgentInput):
            raise ToolError("INVALID_ARGUMENT", "Validated original Agent input is required")
        command = maintenance_plan_command(request)
        if command is None or request.context_id or request.explicit_as_of:
            raise ToolError(
                "INVALID_ARGUMENT", "A new explicit maintenance plan command is required"
            )
        if context.role not in REQUEST_ROLES["MAINTENANCE"]:
            raise ToolError("AUTHORIZATION_DENIED", "Maintenance request permission is required")
        # Resolve retry identity before searching mutable current data. Replaying
        # must retain the saved before/after, not recompute a new proposal.
        try:
            saved = self.store.find_by_retry(
                context, request.retry_key, agent_input_hash=request.input_hash
            )
        except ProposalError as error:
            raise ToolError(error.code, error.message) from error
        if saved is not None:
            return saved
        session = AgentToolSession(
            context, request, self.dispatcher, prepare_authorized=True, event_logger=self.events
        )
        found = session.run(
            "search_maintenance_plans",
            {"filter": {"plan_code": command.plan_code}, "page_size": 2},
        )
        items = found.data["items"]
        if not items:
            raise ToolError("TARGET_NOT_FOUND", "Requested maintenance plan code was not found")
        if len(items) != 1 or found.data["next_cursor"] is not None:
            raise ToolError("TARGET_AMBIGUOUS", "Requested maintenance is not uniquely resolved")
        return session.run(
            "prepare_maintenance_plan_update",
            {"maintenance_plan_id": items[0]["maintenance_plan_id"], "patch": command.patch},
        )
