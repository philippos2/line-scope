"""Agent use case orchestration without HTTP or database connection ownership."""

from dataclasses import dataclass

from ..agent.agent_input import AgentInput
from ..agent.read_agent import ReadAgentResult
from ..agent.update_intent import (
    equipment_state_command,
    maintenance_create_command,
    maintenance_plan_command,
    production_assignment_command,
    production_schedule_command,
)
from ..domain.snapshot import CATEGORIES
from ..execution import ExecutionContext
from .proposals import REQUEST_ROLES, ProposalError
from .reads import ToolError


@dataclass(frozen=True)
class PreparedAgentResult:
    data: dict
    replayed: bool
    error_code: str | None = None


@dataclass(frozen=True)
class AnalyzedAgentResult:
    analysis: ReadAgentResult
    context_id: str | None


class AgentApplication:
    def __init__(
        self,
        *,
        proposals,
        conversations,
        equipment,
        maintenance,
        production,
        read_agent,
        decision_flow=None,
    ):
        self.proposals = proposals
        self.conversations = conversations
        self.commands = (
            (equipment_state_command, equipment),
            (maintenance_plan_command, maintenance),
            (maintenance_create_command, maintenance),
            (production_schedule_command, production),
            (production_assignment_command, production),
        )
        self.read_agent = read_agent
        self.decision_flow = decision_flow

    def run(self, context, incoming, *, retry_requested=False):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if not isinstance(incoming, AgentInput) or type(retry_requested) is not bool:
            raise ToolError("INVALID_ARGUMENT", "Validated Agent input is required")
        if retry_requested:
            saved = self.proposals.find_by_retry(
                context, incoming.retry_key, agent_input_hash=incoming.input_hash
            )
            if saved is not None:
                category = CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]]
                if context.role not in REQUEST_ROLES[category]:
                    raise ToolError("AUTHORIZATION_DENIED", "Prepare retry permission is required")
                return self._prepared(context, saved)
        previous = (
            self.conversations.get(context, incoming.context_id)["messages"]
            if incoming.context_id
            else []
        )
        for recognize, command in self.commands:
            if recognize(incoming) is not None:
                return self._prepared(context, command.run(context, incoming))
        if self.decision_flow is not None and self.decision_flow.matches(incoming.message):
            return self.decision_flow.run(context, incoming)
        if self.read_agent is None:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "LLM is not configured")
        result = self.read_agent.run(
            context,
            incoming,
            previous_messages=previous if incoming.context_id else None,
        )
        context_id = incoming.context_id
        if result.needs_input or context_id:
            stored = {"messages": [*previous, incoming.message]}
            if context_id:
                self.conversations.update(context, context_id, stored)
            else:
                context_id = self.conversations.create(context, stored)
        return AnalyzedAgentResult(result, context_id)

    def _prepared(self, context, saved):
        try:
            data = self.proposals.get(context, saved.update_request_id)
        except ProposalError as error:
            # Prepare already committed; preserve its identity on response-read failure.
            return PreparedAgentResult(
                {
                    "update_request_id": saved.update_request_id,
                    "approval_id": saved.approval_id,
                    "status": saved.status,
                },
                saved.replayed,
                error.code,
            )
        return PreparedAgentResult(data, saved.replayed)
