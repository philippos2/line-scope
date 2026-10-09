from uuid import UUID, uuid4

import pytest
from test_proposals import NOW, context

from linescope.agent_input import AgentInput
from linescope.llm import LLMReply, ToolCall
from linescope.read_agent import ReadAgent
from linescope.reads import ReadResult, ToolError
from linescope.tools import ToolDispatcher


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.requests = []

    def complete(self, messages, *, schemas, deadline):
        from copy import deepcopy

        self.requests.append((deepcopy(messages), schemas, deadline))
        return next(self.replies)


def call(name="get_equipment", arguments=None):
    return LLMReply(
        "", (ToolCall(str(uuid4()), name, arguments or {"equipment_id": str(UUID(int=1))}),)
    )


def request(message="設備M-204を調べて"):
    return AgentInput.parse(context(), '{"message":"' + message + '"}', received_at=NOW)


class Dispatcher:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = 0

    def schemas(self):
        return {
            "get_equipment": {"type": "object"},
            "prepare_equipment_state_update": {"type": "object"},
        }

    def run(self, *args, **kwargs):
        self.calls += 1
        if self.failures:
            raise ToolError(self.failures.pop(0), "Fixed error")
        return ReadResult({"equipment_code": "M-204"}, {"source": "POSTGRESQL", "version": 1})


def test_read_only_schema_and_server_evidence_are_retained():
    llm = ScriptedLLM(call(), LLMReply("M-204を確認しました。", ()))
    result = ReadAgent(Dispatcher(), llm).run(context(), request())
    assert result.answer == "M-204を確認しました。"
    assert result.observations[0].result.evidence == {"source": "POSTGRESQL", "version": 1}
    assert not result.needs_input and not result.errors
    assert "prepare_equipment_state_update" not in llm.requests[0][1]
    assert llm.requests[0][2] == llm.requests[1][2]
    assert llm.requests[1][0][-1]["role"] == "tool"


@pytest.mark.parametrize("code", ["DEPENDENCY_UNAVAILABLE", "RESOURCE_BUSY"])
def test_two_transient_retries_count_against_budget(code):
    dispatcher = Dispatcher([code, code])
    llm = ScriptedLLM(call(), LLMReply("確認できました", ()))
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 3
    assert [item["code"] for item in result.trace] == [code, code, "OK"]
    assert not result.errors


def test_nontransient_error_is_not_retried_or_reported_as_success():
    dispatcher = Dispatcher(["TARGET_NOT_FOUND"])
    llm = ScriptedLLM(call(), LLMReply("存在しません", ()))
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 1 and result.needs_input
    assert result.errors[0]["code"] == "TARGET_NOT_FOUND"
    assert not result.observations


def test_no_tools_means_no_fabricated_business_answer():
    result = ReadAgent(Dispatcher(), ScriptedLLM(LLMReply("設備はすべて安全です", ()))).run(
        context(), request()
    )
    assert result.needs_input and "安全" not in result.answer


def test_call_budget_ends_repeated_calls():
    dispatcher = Dispatcher()
    llm = ScriptedLLM(*[call() for _ in range(13)])
    with pytest.raises(ToolError) as error:
        ReadAgent(dispatcher, llm).run(context(), request())
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert dispatcher.calls == 12
    assert llm.requests[-1][1] == {}


def test_final_explanation_allowed_after_last_call():
    llm = ScriptedLLM(*[call() for _ in range(12)], LLMReply("確認した結果です", ()))
    result = ReadAgent(Dispatcher(), llm).run(context(), request())
    assert len(result.observations) == 12
    assert llm.requests[-1][1] == {}


def test_deadline_after_llm_does_not_dispatch():
    now = [0]

    class Slow(ScriptedLLM):
        def complete(self, *args, **kwargs):
            now[0] = 60
            return call()

    dispatcher = Dispatcher()
    with pytest.raises(ToolError) as error:
        ReadAgent(dispatcher, Slow(), clock=lambda: now[0]).run(context(), request())
    assert error.value.code == "AGENT_LIMIT_REACHED" and dispatcher.calls == 0


def test_real_postgres_search_then_state_and_no_business_updates(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'M-204','Machine','machine',true)",
            (UUID(int=1),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'STOPPED')",
            (UUID(int=1),),
        )
    llm = ScriptedLLM(
        call("search_equipment", {"filter": {"equipment_code": "M-204"}}),
        call("get_equipment_state"),
        LLMReply("M-204はSTOPPEDです。", ()),
    )
    result = ReadAgent(ToolDispatcher(db), llm).run(context(), request())
    assert result.observations[1].result.data["state_code"] == "STOPPED"
    assert all(item.result.evidence["source"] == "POSTGRESQL" for item in result.observations)
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0
        assert (
            connection.execute("SELECT state_code FROM equipment_current_state").fetchone()[
                "state_code"
            ]
            == "STOPPED"
        )


def test_exhausted_transient_retry_retains_error():
    dispatcher = Dispatcher(["RESOURCE_BUSY"] * 3)
    llm = ScriptedLLM(call(), LLMReply("取得できませんでした", ()))
    result = ReadAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 3
    assert result.errors[0]["code"] == "RESOURCE_BUSY"
    assert len(result.trace) == 3 and result.needs_input


def test_prepare_attempt_cannot_reach_dispatcher_even_with_update_message():
    dispatcher = Dispatcher()
    llm = ScriptedLLM(call("prepare_equipment_state_update", {}), LLMReply("変更しました", ()))
    result = ReadAgent(dispatcher, llm).run(
        context(), request("設備M-204の状態をSTOPPEDに変更して")
    )
    assert dispatcher.calls == 0
    assert result.needs_input and "変更しました" not in result.answer
    assert result.errors[0]["code"] == "AUTHORIZATION_DENIED"


def test_known_read_and_unresolved_error_remain_distinct():
    class Partial(Dispatcher):
        def run(self, ctx, name, arguments, **kwargs):
            if arguments["equipment_id"] == str(UUID(int=2)):
                raise ToolError("TARGET_NOT_FOUND", "Missing equipment")
            return super().run(ctx, name, arguments, **kwargs)

    llm = ScriptedLLM(
        call(),
        call(arguments={"equipment_id": str(UUID(int=2))}),
        LLMReply("取得できた分のみ示します", ()),
    )
    result = ReadAgent(Partial(), llm).run(context(), request())
    assert len(result.observations) == 1
    assert result.errors[0]["code"] == "TARGET_NOT_FOUND"


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_id", str(UUID(int=3))),
        ("replace_update_request_id", str(UUID(int=4))),
        ("as_of", "2026-10-08T00:00:00Z"),
    ],
)
def test_unconnected_modes_are_not_silently_ignored(field, value):
    import json

    incoming = AgentInput.parse(
        context(), json.dumps({"message": "query", field: value}), received_at=NOW
    )
    llm = ScriptedLLM()
    with pytest.raises(ToolError) as error:
        ReadAgent(Dispatcher(), llm).run(context(), incoming)
    assert error.value.code == "INVALID_ARGUMENT"
    assert not llm.requests
