import io
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_agent_tools import Dispatcher, session
from test_read_agent import ScriptedLLM, call, request

from linescope.api import create_app
from linescope.demo_seed import DEMO_EQUIPMENT, seed_demo
from linescope.llm import LLMReply
from linescope.logging import EventLogger, current_request_id, request_context
from linescope.read_agent import ReadAgent
from linescope.reads import ToolError
from linescope.settings import Settings

SECRET = "private-message-arguments-token-password-sql"


def captured(dispatcher=None, **kwargs):
    output = io.StringIO()
    events = EventLogger("DEBUG", output)
    return session(dispatcher, event_logger=events, **kwargs), output


def entries(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_success_has_trusted_identity_target_id_and_monotonic_duration(monkeypatch):
    run, output = captured()
    ticks = iter([10_000_000, 15_000_000])
    monkeypatch.setattr("linescope.agent_tools.monotonic_ns", lambda: next(ticks))
    call_id, equipment_id = uuid4(), uuid4()
    with request_context(uuid4(), actor_id="other", role="manager"):
        outer_id = current_request_id()
        run.run(
            "get_equipment",
            {"equipment_id": str(equipment_id), "body": SECRET, "request_id": str(uuid4())},
            tool_call_id=str(call_id),
        )
        assert current_request_id() == outer_id
    (entry,) = entries(output)
    assert entry["request_id"] == str(run.context.request_id)
    assert entry["actor_id"] == run.context.authenticated_user_id
    assert entry["role"] == run.context.role
    assert entry["tool_call_id"] == str(call_id) and entry["equipment_id"] == str(equipment_id)
    assert entry["tool"] == "get_equipment" and entry["event"] == "tool.call.completed"
    assert entry["duration_ms"] == 5 and entry["attempt_count"] == 1
    assert (entry["outcome"], entry["level"], entry["result_code"]) == ("success", "INFO", "OK")
    assert SECRET not in output.getvalue() and "body" not in entry
    assert current_request_id() is None


@pytest.mark.parametrize(
    "code,level,outcome",
    [
        ("TARGET_NOT_FOUND", "INFO", "rejected"),
        ("AUTHORIZATION_DENIED", "INFO", "rejected"),
        ("RESOURCE_BUSY", "WARNING", "failure"),
        ("DEPENDENCY_UNAVAILABLE", "WARNING", "failure"),
        ("INTERNAL_ERROR", "ERROR", "failure"),
    ],
)
def test_tool_errors_preserve_result_and_do_not_log_messages_or_details(code, level, outcome):
    failure = ToolError(code, SECRET, {"sql": SECRET})

    def fail():
        raise failure

    run, output = captured(Dispatcher(fail))
    with pytest.raises(ToolError) as caught:
        run.run("get_equipment", {"equipment_id": SECRET})
    assert caught.value is failure
    (entry,) = entries(output)
    assert (entry["result_code"], entry["level"], entry["outcome"]) == (code, level, outcome)
    assert "equipment_id" not in entry and SECRET not in output.getvalue()
    assert "stack_frames" not in entry
    assert current_request_id() is None


@pytest.mark.parametrize("tool", [SECRET, [SECRET], None, "prepare_equipment_state_update"])
def test_admission_rejection_emits_one_event_without_dispatch_or_unregistered_name(tool):
    dispatcher = Dispatcher()
    run, output = captured(dispatcher)
    with pytest.raises(ToolError):
        run.run(tool, {"prompt": SECRET})
    (entry,) = entries(output)
    assert entry["outcome"] == "rejected" and not dispatcher.calls
    if tool != "prepare_equipment_state_update":
        assert "tool" not in entry
    assert SECRET not in output.getvalue()
    UUID(entry["tool_call_id"])


def test_deadline_rejection_is_logged_without_dispatch():
    now = [0]
    dispatcher = Dispatcher()
    run, output = captured(dispatcher, clock=lambda: now[0])
    now[0] = 60
    with pytest.raises(ToolError):
        run.run("get_equipment", {})
    assert not dispatcher.calls
    (entry,) = entries(output)
    assert entry["result_code"] == "AGENT_LIMIT_REACHED" and entry["outcome"] == "rejected"


def test_unexpected_exception_propagates_without_duplicate_stack_or_secret():
    failure = RuntimeError(SECRET)

    def fail():
        raise failure

    run, output = captured(Dispatcher(fail))
    with pytest.raises(RuntimeError) as caught:
        run.run("get_equipment", {"sql": SECRET})
    assert caught.value is failure
    (entry,) = entries(output)
    assert entry["result_code"] == "INTERNAL_ERROR" and entry["level"] == "ERROR"
    assert "stack_frames" not in entry and SECRET not in output.getvalue()
    assert current_request_id() is None


def test_retries_share_call_id_and_have_individual_attempt_events():
    failures = ["RESOURCE_BUSY", "DEPENDENCY_UNAVAILABLE"]

    def action():
        if failures:
            raise ToolError(failures.pop(0), SECRET)
        from linescope.reads import ReadResult

        return ReadResult({"equipment_code": "M-204"}, {"source": "POSTGRESQL"})

    output = io.StringIO()
    events = EventLogger("DEBUG", output)
    reply = call()
    result = ReadAgent(
        Dispatcher(action), ScriptedLLM(reply, LLMReply("確認しました", ())), event_logger=events
    ).run(session().context, request())
    logged = entries(output)
    assert [row["attempt_count"] for row in logged] == [1, 2, 3]
    assert [row["result_code"] for row in logged] == [
        "RESOURCE_BUSY",
        "DEPENDENCY_UNAVAILABLE",
        "OK",
    ]
    assert {row["tool_call_id"] for row in logged} == {reply.tool_calls[0].call_id}
    assert [row["tool_call_id"] for row in logged] == [row["tool_call_id"] for row in result.trace]
    assert SECRET not in output.getvalue()


def test_concurrent_sessions_do_not_share_request_identity():
    output = io.StringIO()
    events = EventLogger("DEBUG", output)

    def work(_):
        run = session(event_logger=events)
        run.run("get_equipment", {})
        assert current_request_id() is None
        return str(run.context.request_id)

    with ThreadPoolExecutor(max_workers=4) as pool:
        expected = set(pool.map(work, range(12)))
    logged = entries(output)
    assert len(logged) == 12 and {row["request_id"] for row in logged} == expected


def test_output_handler_failure_does_not_change_tool_result(capsys):
    class Broken:
        def write(self, value):
            raise OSError(SECRET)

        def flush(self):
            pass

    run = session(event_logger=EventLogger("DEBUG", Broken()))
    assert run.run("get_equipment", {}).data == {"value": "fact"}
    assert SECRET not in capsys.readouterr().err


@pytest.mark.parametrize("expired", [False, True])
def test_saved_prepare_ids_survive_deadline_without_snapshot_or_retry_key_logging(db, expired):
    from test_proposals import PREPARE_HASH, snapshot

    from linescope.proposals import ProposalStore

    db.migrate()
    now = [0]
    output = io.StringIO()
    run = None

    def action():
        saved = ProposalStore(db).save(
            run.context,
            snapshot(run.context),
            run.request.retry_key,
            prepare_input_hash=PREPARE_HASH,
            agent_input_hash=run.request.input_hash,
        )
        if expired:
            now[0] = 60
        return saved

    run = session(
        Dispatcher(action),
        prepare_authorized=True,
        clock=lambda: now[0],
        event_logger=EventLogger("DEBUG", output),
    )
    if expired:
        with pytest.raises(ToolError) as caught:
            run.run("prepare_equipment_state_update", {})
        assert caught.value.code == "AGENT_LIMIT_REACHED"
    else:
        run.run("prepare_equipment_state_update", {})
    (entry,) = entries(output)
    assert entry["update_request_id"] == str(run.saved_proposal.update_request_id)
    assert entry["approval_id"] == str(run.saved_proposal.approval_id)
    assert entry["snapshot_hash"] == run.saved_proposal.snapshot.snapshot_hash
    assert entry["outcome"] == ("partial" if expired else "success")
    assert str(run.request.retry_key) not in output.getvalue()
    assert "canonical_snapshot" not in entry and "arguments" not in entry


def test_http_threadpool_tool_and_envelope_share_server_request_id(db):
    db.migrate()
    seed_demo(db)
    output = io.StringIO()
    events = EventLogger("DEBUG", output)
    llm = ScriptedLLM(
        call("get_equipment_state", {"equipment_id": str(DEMO_EQUIPMENT[0][0])}),
        LLMReply("M-204はSTOPPEDです", ()),
    )
    settings = Settings(users={SECRET: {"user_id": "floor1", "role": "floor"}})
    with TestClient(create_app(settings, db, events, llm=llm)) as client:
        result = client.post(
            "/agent",
            json={"message": SECRET},
            headers={"Authorization": "Bearer " + SECRET, "X-Request-ID": SECRET},
        )
    assert result.status_code == 200
    relevant = [
        row
        for row in entries(output)
        if row["event"] in {"http.request.completed", "tool.call.completed"}
    ]
    assert len(relevant) == 2
    assert {row["request_id"] for row in relevant} == {result.json()["request_id"]}
    assert all(row["actor_id"] == "floor1" and row["role"] == "floor" for row in relevant)
    tool = next(row for row in relevant if row["component"] == "tool")
    assert tool["tool_call_id"] == result.json()["data"]["tool_trace"][0]["tool_call_id"]
    assert tool["equipment_id"] == str(DEMO_EQUIPMENT[0][0])
    assert SECRET not in output.getvalue() and "STOPPED" not in output.getvalue()
