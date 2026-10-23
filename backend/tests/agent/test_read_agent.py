from uuid import UUID, uuid4

import pytest
from application.test_proposals import NOW, context

from agent.test_graph_model_view import restore
from linescope.agent.agent_input import AgentInput
from linescope.agent.read_agent import ReadAgent as BoundaryReadAgent
from linescope.application.reads import ReadResult, ToolError
from linescope.application.tools import ToolDispatcher
from linescope.integrations.llm import LLMError, LLMReply, ToolCall


class ScriptedLLM:
    def __init__(self, *replies, subjects=()):
        from linescope.agent.read_scope import TOPICS

        tools = {call.name for reply in replies for call in reply.tool_calls}
        self.scope_topics = getattr(
            self,
            "scope_topics",
            tuple(name for name, (_, admitted) in TOPICS.items() if tools & admitted)
            or ("ATTRIBUTES",),
        )
        self.scope_subjects = list(subjects)
        self.replies = iter(replies)
        self.requests = []
        self.planning_requests = []

    def complete(self, messages, *, schemas, deadline):
        from copy import deepcopy

        from linescope.agent.read_scope import FIELDS, PLAN_TOOL
        from linescope.agent.scope_check import CHECK_TOOL

        if CHECK_TOOL in schemas:
            return call(CHECK_TOOL, {"verdict": "MATCH"})

        if PLAN_TOOL in schemas:
            # These existing tests exercise retrieval, not model intent accuracy.
            # Planning is separately recorded and tested in test_grounded_answer.
            self.planning_requests.append((deepcopy(messages), schemas, deadline))
            return call(
                PLAN_TOOL,
                {
                    "source_spans": [
                        {
                            "text": messages[-1]["content"],
                        }
                    ],
                    "topics": list(self.scope_topics),
                    "subjects": self.scope_subjects,
                    "requested_fields": [
                        next(
                            (field for field, topic in FIELDS.items() if topic == chosen),
                            "unsupported",
                        )
                        for chosen in self.scope_topics
                    ],
                },
            )
        self.requests.append((deepcopy(messages), schemas, deadline))
        return next(self.replies)


class AdmittedPlanAgent(BoundaryReadAgent):
    """Unit harness for the admitted-plan executor, not the public question gate.

    Existing executor assertions (budget/retry/evidence/Tool admission) stay intact.
    H6 public admission and confirmation are tested in test_read_confirmation.
    """

    def run(self, context, request, *, previous_messages=None):
        from linescope.agent.agent_tools import AgentToolSession
        from linescope.agent.read_scope import classify

        if request.message.startswith("関係分析 "):
            return super().run(context, request, previous_messages=previous_messages)
        session = AgentToolSession(
            context,
            request,
            self.dispatcher,
            clock=self.clock,
            event_logger=self.events,
            deadline_seconds=self.deadline_seconds,
        )
        if (request.context_id and previous_messages is None) or request.replace_update_request_id:
            raise ToolError("INVALID_ARGUMENT", "This read loop requires a valid read context")
        scope = classify(self.llm, request, session, previous_messages)
        return self._execute_scope(context, request, session, scope, previous_messages)


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
    result = AdmittedPlanAgent(Dispatcher(), llm).run(context(), request())
    assert "M-204" in result.answer and result.answer != "M-204を確認しました。"
    assert result.answer_sections["facts"][0]["predicate"] == "equipment.identity"
    assert result.answer_sections["facts"][0]["references"] == [result.observations[0].tool_call_id]
    assert result.observations[0].result.evidence == {"source": "POSTGRESQL", "version": 1}
    assert not result.needs_input and not result.errors
    assert "prepare_equipment_state_update" not in llm.requests[0][1]
    assert llm.requests[0][2] == llm.requests[1][2]
    assert llm.requests[1][0][-1]["role"] == "tool"


@pytest.mark.parametrize("code", ["DEPENDENCY_UNAVAILABLE", "RESOURCE_BUSY"])
def test_two_transient_retries_count_against_budget(code):
    dispatcher = Dispatcher([code, code])
    llm = ScriptedLLM(call(), LLMReply("確認できました", ()))
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 3
    assert [item["code"] for item in result.trace] == [code, code, "OK"]
    assert not result.errors


def test_nontransient_error_is_not_retried_or_reported_as_success():
    dispatcher = Dispatcher(["TARGET_NOT_FOUND"])
    llm = ScriptedLLM(call(), LLMReply("存在しません", ()))
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 1 and result.needs_input
    assert result.errors[0]["code"] == "TARGET_NOT_FOUND"
    assert not result.observations


def test_no_tools_means_no_fabricated_business_answer():
    result = AdmittedPlanAgent(Dispatcher(), ScriptedLLM(LLMReply("設備はすべて安全です", ()))).run(
        context(), request()
    )
    assert result.needs_input and "安全" not in result.answer


def test_call_budget_ends_repeated_calls():
    dispatcher = Dispatcher()
    llm = ScriptedLLM(*[call() for _ in range(13)])
    with pytest.raises(ToolError) as error:
        AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert dispatcher.calls == 12
    assert llm.requests[-1][1] == {}


def test_final_explanation_allowed_after_last_call():
    llm = ScriptedLLM(*[call() for _ in range(12)], LLMReply("確認した結果です", ()))
    result = AdmittedPlanAgent(Dispatcher(), llm).run(context(), request())
    assert len(result.observations) == 12
    assert llm.requests[-1][1] == {}


@pytest.mark.parametrize("deadline_seconds", [60, 90, 120])
def test_deadline_after_llm_does_not_dispatch(deadline_seconds):
    now = [0]

    class Slow(ScriptedLLM):
        def complete(self, *args, **kwargs):
            now[0] = deadline_seconds
            return call()

    dispatcher = Dispatcher()
    with pytest.raises(ToolError) as error:
        AdmittedPlanAgent(
            dispatcher, Slow(), clock=lambda: now[0], deadline_seconds=deadline_seconds
        ).run(context(), request())
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
    result = AdmittedPlanAgent(ToolDispatcher(db), llm).run(context(), request())
    assert [
        item.result.data["state_code"]
        for item in result.observations
        if item.tool == "get_equipment_state"
    ] == ["STOPPED"]
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
    result = AdmittedPlanAgent(dispatcher, llm).run(context(), request())
    assert dispatcher.calls == 3
    assert result.errors[0]["code"] == "RESOURCE_BUSY"
    assert len(result.trace) == 3 and not result.needs_input


def test_prepare_attempt_cannot_reach_dispatcher_even_with_update_message():
    dispatcher = Dispatcher()
    llm = ScriptedLLM(call("prepare_equipment_state_update", {}), LLMReply("変更しました", ()))
    result = AdmittedPlanAgent(dispatcher, llm).run(
        context(), request("設備M-204の状態をSTOPPEDに変更して")
    )
    assert dispatcher.calls == 0
    assert not result.needs_input and "変更しました" not in result.answer
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
    result = AdmittedPlanAgent(Partial(), llm).run(context(), request())
    assert len(result.observations) == 1
    assert result.errors[0]["code"] == "TARGET_NOT_FOUND"


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_id", str(UUID(int=3))),
        ("replace_update_request_id", str(UUID(int=4))),
    ],
)
def test_unconnected_modes_are_not_silently_ignored(field, value):
    import json

    incoming = AgentInput.parse(
        context(), json.dumps({"message": "query", field: value}), received_at=NOW
    )
    llm = ScriptedLLM()
    with pytest.raises(ToolError) as error:
        AdmittedPlanAgent(Dispatcher(), llm).run(context(), incoming)
    assert error.value.code == "INVALID_ARGUMENT"
    assert not llm.requests


@pytest.mark.parametrize(
    "code", ["DEPENDENCY_UNAVAILABLE", "AGENT_LIMIT_REACHED", "INTERNAL_ERROR"]
)
def test_provider_failure_is_translated_without_tool_execution(code):
    class FailedProvider:
        def complete(self, messages, *, schemas, deadline):
            raise LLMError(code, "Sanitized provider failure")

    dispatcher = Dispatcher()
    with pytest.raises(ToolError) as error:
        AdmittedPlanAgent(dispatcher, FailedProvider()).run(context(), request())
    assert error.value.code == code
    assert error.value.message == "Sanitized provider failure"
    assert error.value.details == {}
    assert isinstance(error.value.__cause__, LLMError)
    assert dispatcher.calls == 0


@pytest.mark.parametrize("tool", ["trace_downstream_impact", "trace_upstream_dependencies"])
def test_graph_paths_are_sent_once_without_mutating_server_evidence(tool):
    from linescope.agent.read_agent import model_tool_payload

    paths = [{"nodes": ["root", "target"], "edges": ["SUPPLIES"]}]
    result = ReadResult(
        {"representative_paths": paths},
        {
            "representative_paths": paths,
            "source": "NEO4J_AND_POSTGRESQL",
            "graph_generation": "g1",
        },
    )
    payload = model_tool_payload(tool, result)
    assert restore(payload["data"], payload)["representative_paths"] == paths
    assert "representative_paths" not in payload["evidence"]
    assert payload["evidence"]["representative_paths_location"] == "data.representative_paths"
    assert payload["evidence"]["graph_generation"] == "g1"
    assert result.evidence["representative_paths"] == paths


def test_distinct_graph_paths_are_not_silently_discarded():
    from linescope.agent.read_agent import model_tool_payload

    result = ReadResult(
        {"representative_paths": ["data-path"]}, {"representative_paths": ["evidence-path"]}
    )
    assert model_tool_payload("trace_downstream_impact", result)["evidence"] == result.evidence
    assert model_tool_payload("get_equipment", result)["evidence"] == result.evidence


def test_agent_graph_model_view_and_returned_evidence_are_separate():
    import json

    paths = [{"nodes": ["root", "target"], "edges": ["SUPPLIES"]}]
    result = ReadResult({"representative_paths": paths}, {"representative_paths": paths})

    class GraphDispatcher(Dispatcher):
        def schemas(self):
            return {"trace_downstream_impact": {"type": "object"}}

        def run(self, *args, **kwargs):
            return result

    llm = ScriptedLLM(call("trace_downstream_impact", {}), LLMReply("経路を確認しました。", ()))
    outcome = AdmittedPlanAgent(GraphDispatcher(), llm).run(context(), request())
    payload = json.loads(llm.requests[-1][0][-1]["content"])
    assert restore(payload["data"], payload)["representative_paths"] == paths
    assert "representative_paths" not in payload["evidence"]
    assert outcome.observations[0].result.evidence["representative_paths"] == paths


def explicit_request(command, **extra):
    import json

    return AgentInput.parse(
        context(),
        json.dumps({"message": "関係分析 " + json.dumps(command), **extra}),
        received_at=NOW,
    )


def test_explicit_graph_selection_preserves_ids_and_evidence_without_llm():
    selected = [{"entity_type": "Product", "entity_id": str(UUID(int=4))}]
    arguments = {"important_targets": selected, "candidate_nodes": []}

    class SelectedDispatcher(Dispatcher):
        def schemas(self):
            return {"find_single_point_failure_candidates": {"type": "object"}}

        def run(self, ctx, tool, supplied, **kwargs):
            assert ctx.authenticated_user_id == "floor1"
            assert tool == "find_single_point_failure_candidates"
            assert supplied == arguments
            return ReadResult(
                {"findings": [], "complete": True}, {"source": "NEO4J_AND_POSTGRESQL"}
            )

    llm = ScriptedLLM()
    result = AdmittedPlanAgent(SelectedDispatcher(), llm).run(
        context(),
        explicit_request({"tool": "find_single_point_failure_candidates", "arguments": arguments}),
    )
    assert not llm.requests
    assert result.observations[0].result.data["findings"] == []
    assert result.observations[0].result.evidence["source"] == "NEO4J_AND_POSTGRESQL"


@pytest.mark.parametrize(
    "command",
    [
        {"tool": "prepare_equipment_state_update", "arguments": {}},
        {"tool": "execute", "arguments": {}},
        {"tool": "get_equipment", "arguments": {}, "role": "manager"},
        {"tool": "get_equipment", "arguments": None},
        {"tool": [], "arguments": {}},
    ],
)
def test_explicit_graph_rejects_writes_and_malformed_commands(command):
    dispatcher, llm = Dispatcher(), ScriptedLLM()
    with pytest.raises(ToolError, match="Invalid explicit graph investigation"):
        AdmittedPlanAgent(dispatcher, llm).run(context(), explicit_request(command))
    assert dispatcher.calls == 0 and not llm.requests


def test_explicit_graph_uses_existing_authorization_failure():
    dispatcher = Dispatcher(["AUTHORIZATION_DENIED"])
    llm = ScriptedLLM()
    with pytest.raises(ToolError) as error:
        AdmittedPlanAgent(dispatcher, llm).run(
            context(),
            explicit_request(
                {
                    "tool": "get_equipment",
                    "arguments": {"equipment_id": str(UUID(int=1))},
                }
            ),
        )
    assert error.value.code == "AUTHORIZATION_DENIED"
    assert dispatcher.calls == 1 and not llm.requests


def test_explicit_graph_does_not_bypass_uuid_argument_validation():
    llm = ScriptedLLM()
    with pytest.raises(ToolError) as error:
        AdmittedPlanAgent(ToolDispatcher(None), llm).run(
            context(),
            explicit_request(
                {
                    "tool": "get_equipment",
                    "arguments": {"equipment_id": "not-a-uuid"},
                }
            ),
        )
    assert error.value.code == "INVALID_ARGUMENT"
    assert not llm.requests
