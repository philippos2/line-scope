"""Explicit original-message JSON through existing authorized Prepare contracts."""

from ..agent.agent_input import AgentInput
from ..agent.agent_tools import AgentToolSession
from ..agent.update_intent import structured_prepare_command
from ..domain.canonical import strict_json
from ..execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .reads import ToolError
from .tools import PREPARE_CATEGORIES, ToolDispatcher


class StructuredCommandPrepare:
    def __init__(self, database, *, event_logger=None):
        self.store, self.dispatcher = ProposalStore(database), ToolDispatcher(database)
        self.events = event_logger

    def run(self, context, request):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if not isinstance(request, AgentInput):
            raise ToolError("INVALID_ARGUMENT", "Validated original input is required")
        command = structured_prepare_command(request)
        if command is None or request.context_id or request.explicit_as_of:
            raise ToolError("INVALID_ARGUMENT", "A new explicit Prepare command is required")
        category, encoded = command
        if context.role not in REQUEST_ROLES[category]:
            raise ToolError("AUTHORIZATION_DENIED", "Prepare category permission is required")
        try:
            values = strict_json(encoded)
            if type(values) is not dict or set(values) != {"targets"}:
                raise ValueError("Invalid fields")
            targets = values["targets"]
            if type(targets) is not list or not 1 <= len(targets) <= 10:
                raise ValueError("Invalid target count")
            for target in targets:
                if type(target) is not dict or set(target) != {"prepare_tool", "input"}:
                    raise ValueError("Invalid target")
                tool = target["prepare_tool"]
                if type(tool) is not str or tool not in PREPARE_CATEGORIES:
                    raise ValueError("Only registered Prepare Tools are permitted")
                if PREPARE_CATEGORIES[tool] != category:
                    raise ToolError(
                        "BUSINESS_RULE_VIOLATION", "All targets must share the category"
                    )
                if type(target["input"]) is not dict:
                    raise ValueError("Invalid input")
        except (ValueError, TypeError) as error:
            raise ToolError("INVALID_ARGUMENT", "Invalid structured Prepare input") from error
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
        return session.run(targets[0]["prepare_tool"], values)
