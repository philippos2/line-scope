from uuid import UUID

import pytest
from test_proposals import NOW, context

from linescope.agent_input import AgentInput
from linescope.agent_tools import AgentToolSession
from linescope.reads import ReadResult, ToolError

PREPARE = "prepare_equipment_state_update"


class Dispatcher:
    def __init__(self, action=None):
        self.calls = []
        self.action = action

    def schemas(self):
        return {"get_equipment": {"type": "object"}, PREPARE: {"type": "object"}}

    def run(self, ctx, tool, args, **metadata):
        self.calls.append((ctx, tool, args, metadata))
        return (
            self.action()
            if self.action
            else ReadResult({"value": "fact"}, {"source": "POSTGRESQL"})
        )


def session(dispatcher=None, **kwargs):
    owner = context()
    request = AgentInput.parse(
        owner, '{"message":"設備を検索"}', received_at=NOW, idempotency_key=str(UUID(int=1))
    )
    return AgentToolSession(owner, request, dispatcher or Dispatcher(), **kwargs)


def test_default_call_limit_and_attempts_count_errors():
    dispatcher = Dispatcher()
    run = session(dispatcher)
    for _ in range(12):
        run.run("get_equipment", {})
    with pytest.raises(ToolError) as error:
        run.run("get_equipment", {})
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert len(dispatcher.calls) == run.calls == 12
    run = session(max_calls=1)
    with pytest.raises(ToolError):
        run.run("execute", {})
    with pytest.raises(ToolError) as error:
        run.run("get_equipment", {})
    assert error.value.code == "AGENT_LIMIT_REACHED"


@pytest.mark.parametrize(
    "name", ["execute", "approve", "sql", "cypher", None, [], "trace_downstream_impact"]
)
def test_unregistered_tools_do_not_dispatch(name):
    dispatcher = Dispatcher()
    run = session(dispatcher)
    with pytest.raises(ToolError) as error:
        run.run(name, {})
    assert error.value.code == "INVALID_ARGUMENT"
    assert not dispatcher.calls


def test_prepare_hidden_and_denied_until_server_authorizes():
    dispatcher = Dispatcher()
    run = session(dispatcher)
    assert PREPARE not in run.schemas()
    with pytest.raises(ToolError) as error:
        run.run(PREPARE, {"prepare_authorized": True})
    assert error.value.code == "AUTHORIZATION_DENIED"
    assert not dispatcher.calls
    schemas = run.schemas()
    schemas["get_equipment"]["type"] = "string"
    assert run.schemas()["get_equipment"]["type"] == "object"


def test_prepare_metadata_is_trusted_and_only_one_attempt_per_turn():
    dispatcher = Dispatcher()
    run = session(dispatcher, prepare_authorized=True)
    assert PREPARE in run.schemas()
    run.run(PREPARE, {"equipment_id": "id"})
    ctx, tool, args, metadata = dispatcher.calls[0]
    assert ctx == run.context
    assert metadata == {
        "retry_key": str(UUID(int=1)),
        "agent_input_hash": run.request.input_hash,
        "supersedes_update_request_id": None,
    }
    with pytest.raises(ToolError) as error:
        run.run(PREPARE, {})
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert len(dispatcher.calls) == 1


@pytest.mark.parametrize("elapsed", [60, 61])
def test_deadline_prevents_new_dispatch_at_boundary(elapsed):
    now = [0]
    dispatcher = Dispatcher()
    run = session(dispatcher, clock=lambda: now[0])
    now[0] = elapsed
    with pytest.raises(ToolError) as error:
        run.run("get_equipment", {})
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert not dispatcher.calls


def test_deadline_after_read_does_not_return_success():
    now = [0]

    def action():
        now[0] = 60
        return ReadResult({}, {})

    run = session(Dispatcher(action), clock=lambda: now[0])
    with pytest.raises(ToolError) as error:
        run.run("get_equipment", {})
    assert error.value.code == "AGENT_LIMIT_REACHED"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_calls": 0},
        {"max_calls": True},
        {"max_calls": 1.5},
        {"deadline_seconds": 0},
        {"deadline_seconds": float("inf")},
        {"deadline_seconds": float("nan")},
        {"deadline_seconds": True},
        {"prepare_authorized": "true"},
    ],
)
def test_invalid_budget_configuration(kwargs):
    with pytest.raises(ValueError):
        session(**kwargs)


def test_saved_prepare_is_preserved_if_deadline_expires(db):
    from test_proposals import PREPARE_HASH, snapshot

    from linescope.proposals import ProposalStore

    db.migrate()
    now = [0]
    owner = context()
    request = AgentInput.parse(owner, '{"message":"設備状態を変更"}', received_at=NOW)

    def action():
        saved = ProposalStore(db).save(
            owner,
            snapshot(owner),
            request.retry_key,
            prepare_input_hash=PREPARE_HASH,
            agent_input_hash=request.input_hash,
        )
        now[0] = 60
        return saved

    dispatcher = Dispatcher(action)
    run = AgentToolSession(
        owner, request, dispatcher, prepare_authorized=True, clock=lambda: now[0]
    )
    with pytest.raises(ToolError) as error:
        run.run(PREPARE, {})
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert error.value.details["update_request_id"] == str(run.saved_proposal.update_request_id)
    retry = ProposalStore(db).find_by_retry(
        owner, request.retry_key, agent_input_hash=request.input_hash
    )
    assert retry.update_request_id == run.saved_proposal.update_request_id


def test_real_dispatcher_read_and_prepare_keep_business_state_unchanged(db):
    from linescope.tools import ToolDispatcher

    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'EQ','Machine','machine',true)",
            (UUID(int=100),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'RUNNING')",
            (UUID(int=100),),
        )
    run = session(ToolDispatcher(db), prepare_authorized=True)
    assert isinstance(run.run("get_equipment", {"equipment_id": str(UUID(int=100))}), ReadResult)
    saved = run.run(PREPARE, {"equipment_id": str(UUID(int=100)), "state_code": "STOPPED"})
    assert saved == run.saved_proposal
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT state_code FROM equipment_current_state").fetchone()[
                "state_code"
            ]
            == "RUNNING"
        )
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 1


def test_failed_prepare_is_not_automatically_retried():
    def action():
        raise ToolError("TARGET_AMBIGUOUS", "Select a target")

    dispatcher = Dispatcher(action)
    run = session(dispatcher, prepare_authorized=True)
    with pytest.raises(ToolError) as error:
        run.run(PREPARE, {})
    assert error.value.code == "TARGET_AMBIGUOUS"
    with pytest.raises(ToolError) as error:
        run.run(PREPARE, {})
    assert error.value.code == "AGENT_LIMIT_REACHED"
    assert len(dispatcher.calls) == 1


def test_parallel_admission_cannot_exceed_budget():
    from concurrent.futures import ThreadPoolExecutor

    run = session(max_calls=1)

    def call(_):
        try:
            run.run("get_equipment", {})
            return "OK"
        except ToolError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(call, range(4)))
    assert results.count("OK") == 1
    assert results.count("AGENT_LIMIT_REACHED") == 3
    assert run.calls == 1
