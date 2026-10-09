"""Per-request Agent Tool admission, accounting and saved-proposal preservation.

prepare_authorized is a trusted server enable switch, never an LLM argument.
Original-message intent must also pass the conservative server grammar.
This synchronous boundary checks deadlines between calls; dependency timeout
propagation and the LLM deadline are separate integration work.
"""

from math import isfinite
from threading import Lock
from time import monotonic

from .agent_input import AgentInput
from .execution import ExecutionContext
from .proposals import SavedProposal
from .reads import ToolError
from .tools import PREPARE_CATEGORIES
from .update_intent import assess_update_intent


class AgentToolSession:
    def __init__(
        self,
        context,
        request,
        dispatcher,
        *,
        prepare_authorized=False,
        max_calls=12,
        deadline_seconds=60,
        clock=monotonic,
    ):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if not isinstance(request, AgentInput):
            raise ValueError("A validated Agent input is required")
        if type(prepare_authorized) is not bool:
            raise ValueError("Prepare authorization must be a server boolean")
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError("Tool limit must be a positive integer")
        if (
            type(deadline_seconds) not in (int, float)
            or not isfinite(deadline_seconds)
            or deadline_seconds <= 0
        ):
            raise ValueError("Agent deadline must be positive and finite")
        self.context, self.request, self.dispatcher = context, request, dispatcher
        self.update_intent = assess_update_intent(request)
        self.prepare_authorized = prepare_authorized and self.update_intent.confirmed
        self.max_calls, self.clock = max_calls, clock
        self.deadline = clock() + deadline_seconds
        self.calls = 0
        self._prepare_started = False
        self._proposal = None
        self._lock = Lock()
        self._schemas = dispatcher.schemas()

    @property
    def saved_proposal(self):
        with self._lock:
            return self._proposal

    def _limit_error(self):
        details = {}
        if self._proposal is not None:
            details = {
                "update_request_id": str(self._proposal.update_request_id),
                "approval_id": str(self._proposal.approval_id),
                "status": self._proposal.status,
            }
        return ToolError("AGENT_LIMIT_REACHED", "Agent execution budget was exhausted", details)

    def check_deadline(self):
        """Also called by the future orchestrator before/after LLM work."""
        with self._lock:
            if self.clock() >= self.deadline:
                raise self._limit_error()

    def schemas(self):
        from copy import deepcopy

        return deepcopy(
            {
                name: schema
                for name, schema in self._schemas.items()
                if name not in PREPARE_CATEGORIES
                or (
                    self.prepare_authorized
                    and PREPARE_CATEGORIES[name] == self.update_intent.category
                )
            }
        )

    def run(self, tool, arguments):
        with self._lock:
            if self.clock() >= self.deadline or self.calls >= self.max_calls:
                raise self._limit_error()
            # Rejected calls consume budget too; retries cannot bypass accounting.
            self.calls += 1
            if type(tool) is not str or tool not in self._schemas:
                raise ToolError("INVALID_ARGUMENT", "Unknown Agent Tool")
            prepare = tool in PREPARE_CATEGORIES
            if prepare and (
                not self.prepare_authorized
                or PREPARE_CATEGORIES[tool] != self.update_intent.category
            ):
                raise ToolError("AUTHORIZATION_DENIED", "Explicit update intent must be confirmed")
            if prepare:
                if self._prepare_started:
                    raise self._limit_error()
                # Reserve before dispatch, including failed/ambiguous attempts.
                # A new turn may retry with the same persisted retry identity.
                self._prepare_started = True
        try:
            result = self.dispatcher.run(
                self.context,
                tool,
                arguments,
                retry_key=self.request.retry_key,
                agent_input_hash=self.request.input_hash,
                supersedes_update_request_id=self.request.replace_update_request_id,
            )
        except ToolError:
            self.check_deadline()
            raise
        with self._lock:
            if isinstance(result, SavedProposal):
                self._proposal = result
            if self.clock() >= self.deadline:
                raise self._limit_error()
        return result
