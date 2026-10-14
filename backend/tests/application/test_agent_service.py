from types import SimpleNamespace
from uuid import uuid4

import pytest

from linescope.agent.agent_input import AgentInput, ConversationStore
from linescope.agent.read_agent import ReadAgentResult
from linescope.application.agent_service import AgentApplication, PreparedAgentResult
from linescope.application.proposals import ProposalError
from linescope.application.reads import ToolError
from linescope.execution import ExecutionContext


def context(role="manager"):
    return ExecutionContext("operator", role, uuid4())


def incoming(context_id=None):
    return AgentInput("影響を教えて", context_id, None, None, str(uuid4()))


def service(**ports):
    return AgentApplication(
        **dict(
            proposals=None,
            conversations=ConversationStore(),
            equipment=None,
            maintenance=None,
            production=None,
            read_agent=None,
        )
        | ports
    )


def test_read_requires_configured_dependency():
    with pytest.raises(ToolError) as error:
        service().run(context(), incoming())
    assert error.value.code == "DEPENDENCY_UNAVAILABLE"


def test_clarification_messages_are_preserved_across_requests():
    identity = context()
    conversations = ConversationStore()
    seen = []

    class Reader:
        def run(self, context, request, *, previous_messages):
            seen.append(previous_messages)
            return ReadAgentResult("対象を確認", (), (), (), True)

    application = service(conversations=conversations, read_agent=Reader())
    first = application.run(identity, incoming())
    second = application.run(identity, incoming(first.context_id))
    assert first.context_id == second.context_id
    assert seen == [None, ["影響を教えて"]]
    assert conversations.get(identity, second.context_id)["messages"] == [
        "影響を教えて",
        "影響を教えて",
    ]


def test_retry_precedes_expired_conversation_and_preserves_durable_identity():
    saved = SimpleNamespace(
        snapshot=SimpleNamespace(data={"targets": [{"target_type": "EquipmentState"}]}),
        update_request_id=str(uuid4()),
        approval_id=str(uuid4()),
        status="WAITING_APPROVAL",
        replayed=True,
    )

    class Proposals:
        def find_by_retry(self, context, key, *, agent_input_hash):
            return saved

        def get(self, context, identity):
            raise ProposalError("DEPENDENCY_UNAVAILABLE", "Unavailable")

    result = service(proposals=Proposals()).run(
        context(), incoming(str(uuid4())), retry_requested=True
    )
    assert isinstance(result, PreparedAgentResult)
    assert result.error_code == "DEPENDENCY_UNAVAILABLE"
    assert result.replayed
    assert result.data == {
        "update_request_id": saved.update_request_id,
        "approval_id": saved.approval_id,
        "status": saved.status,
    }


def test_untrusted_context_cannot_enter_application():
    with pytest.raises(ToolError) as error:
        service().run(None, incoming())
    assert error.value.code == "AUTHENTICATION_REQUIRED"


def test_clarification_retains_request_time_and_explicit_change_takes_precedence():
    from dataclasses import replace

    identity = context()
    conversations = ConversationStore()
    seen = []

    class Reader:
        def run(self, context, request, *, previous_messages):
            seen.append(request.explicit_as_of)
            return ReadAgentResult("対象を確認", (), (), (), True)

    application = service(conversations=conversations, read_agent=Reader())
    old_time, new_time = "2026-10-08T00:00:00.000000Z", "2026-10-09T00:00:00.000000Z"
    first = application.run(identity, replace(incoming(), explicit_as_of=old_time))
    application.run(identity, incoming(first.context_id))
    application.run(identity, replace(incoming(first.context_id), explicit_as_of=new_time))
    assert seen == [old_time, old_time, new_time]
    assert conversations.get(identity, first.context_id)["explicit_as_of"] == new_time
