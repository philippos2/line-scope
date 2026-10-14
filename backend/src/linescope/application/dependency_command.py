"""Explicit dependency input admitted to the existing authorized Prepare path.

Structured values are original-request data, never LLM-generated authority.
The existing Tool/Prepare validates endpoint types, references, periods,
duplicates and cycles. No Approval/Execute is performed here.
"""

from ..agent.agent_input import AgentInput
from ..agent.agent_tools import AgentToolSession
from ..agent.update_intent import dependency_command
from ..domain.canonical import strict_json
from ..execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .reads import ToolError
from .tools import ToolDispatcher


class DependencyCommandPrepare:
    def __init__(self, database, *, event_logger=None):
        self.store = ProposalStore(database)
        self.dispatcher = ToolDispatcher(database)
        self.events = event_logger

    def run(self, context, request):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if not isinstance(request, AgentInput):
            raise ToolError("INVALID_ARGUMENT", "Validated original Agent input is required")
        command = dependency_command(request)
        if command is None or request.context_id or request.explicit_as_of:
            raise ToolError("INVALID_ARGUMENT", "A new explicit dependency command is required")
        if context.role not in REQUEST_ROLES["DEPENDENCY"]:
            raise ToolError("AUTHORIZATION_DENIED", "Dependency request permission is required")
        try:
            saved = self.store.find_by_retry(
                context, request.retry_key, agent_input_hash=request.input_hash
            )
        except ProposalError as error:
            raise ToolError(error.code, error.message) from error
        if saved is not None:
            return saved
        try:
            values = strict_json(command.values_json) if command.values_json is not None else {}
            if type(values) is not dict or "operation_type" in values:
                raise ValueError("Invalid dependency values")
        except (ValueError, TypeError):
            raise ToolError("INVALID_ARGUMENT", "Invalid dependency values") from None
        if command.operation == "CREATE":
            arguments = {"operation_type": "CREATE", **values}
        else:
            arguments = {
                "operation_type": command.operation,
                "dependency_relation_id": command.identifier,
            }
            if command.operation == "UPDATE":
                arguments["patch"] = values
        session = AgentToolSession(
            context, request, self.dispatcher, prepare_authorized=True, event_logger=self.events
        )
        return session.run("prepare_dependency_relation_update", arguments)
