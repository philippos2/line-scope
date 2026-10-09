from uuid import UUID

import pytest
from test_proposals import NOW, context

from linescope.agent_input import AgentInput, ConversationStore
from linescope.proposals import ProposalError


def parse(body, key=None):
    return AgentInput.parse(context(), body, received_at=NOW, idempotency_key=key)


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"[]",
        b'{"message":null}',
        b'{"message":1}',
        b'{"message":" "}',
        b'{"message":"x","role":"manager"}',
        b'{"message":"x","user_id":"other"}',
        b'{"message":"x","message":"y"}',
        b'{"message":"x","as_of":null}',
        b'{"message":"x","context_id":null}',
        b'{"message":"x","replace_update_request_id":"bad"}',
        b'{"message":"x","as_of":"2026-10-09T00:00:01Z"}',
        b'{"message":"x","as_of":"2026-10-08"}',
        b'{"message":"\\ud800"}',
        b'{"message":"x","number":1.2}',
        b"\xff",
    ],
)
def test_invalid_agent_input(body):
    with pytest.raises(ProposalError) as error:
        parse(body)
    assert error.value.code == "INVALID_ARGUMENT"


def test_request_hash_normalizes_uuid_and_time_but_preserves_original_message():
    a = parse(
        '{"message":"設備を検索","context_id":"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA","as_of":"2026-10-09T09:00:00+09:00"}',
        str(UUID(int=1)),
    )
    b = parse(
        '{"as_of":"2026-10-09T00:00:00Z","context_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","message":"設備を検索"}',
        str(UUID(int=2)),
    )
    assert a.input_hash == b.input_hash
    assert a.retry_key != b.retry_key
    assert parse('{"message":"x"}').input_hash != parse('{"message":" x"}').input_hash
    UUID(parse('{"message":"x"}').retry_key)


@pytest.mark.parametrize(
    "field,value",
    [
        ("message", "other"),
        ("context_id", str(UUID(int=2))),
        ("as_of", "2026-10-08T00:00:00Z"),
        ("replace_update_request_id", str(UUID(int=3))),
    ],
)
def test_each_hash_field_changes_retry_identity(field, value):
    import json

    assert (
        parse(json.dumps({"message": "x", field: value})).input_hash
        != parse('{"message":"x"}').input_hash
    )


def test_invalid_header_and_unauthenticated_input():
    with pytest.raises(ProposalError) as error:
        parse('{"message":"x"}', "bad")
    assert error.value.code == "INVALID_ARGUMENT"
    with pytest.raises(ProposalError) as error:
        AgentInput.parse(None, b"bad", received_at=NOW)
    assert error.value.code == "AUTHENTICATION_REQUIRED"


@pytest.mark.parametrize("ttl", [0, -1, True, float("inf"), float("nan"), "30"])
def test_invalid_ttl(ttl):
    with pytest.raises(ValueError):
        ConversationStore(ttl_seconds=ttl)


def test_context_owner_copy_isolation_and_last_update_ttl():
    now = [0.0]
    store = ConversationStore(clock=lambda: now[0])
    owner = context()
    data = {"candidates": [{"id": "equipment-id", "name": "Machine"}]}
    identity = store.create(owner, data)
    data["candidates"].clear()
    assert len(store.get(owner, identity)["candidates"]) == 1
    exposed = store.get(owner, identity)
    exposed["candidates"].clear()
    assert len(store.get(owner, identity)["candidates"]) == 1
    for operation in (
        lambda: store.get(context("other"), identity),
        lambda: store.update(context("other"), identity, {}),
    ):
        with pytest.raises(ProposalError) as error:
            operation()
        assert error.value.code == "AUTHORIZATION_DENIED"
    now[0] = 1799
    store.update(owner, identity, {"selected": "equipment-id"})
    now[0] = 3598
    assert store.get(context("floor1", "manager"), identity)["selected"] == "equipment-id"
    now[0] = 3599
    with pytest.raises(ProposalError) as error:
        store.get(owner, identity)
    assert error.value.code == "CONTEXT_EXPIRED"


def test_context_read_does_not_extend_ttl_restart_and_missing_reject():
    now = [0.0]
    store = ConversationStore(clock=lambda: now[0])
    owner = context()
    identity = store.create(owner, {})
    now[0] = 1799
    assert store.get(owner, identity) == {}
    now[0] = 1800
    for current in (store, ConversationStore()):
        with pytest.raises(ProposalError) as error:
            current.get(owner, identity)
        assert error.value.code == "CONTEXT_EXPIRED"
    with pytest.raises(ProposalError) as error:
        store.get(owner, "bad")
    assert error.value.code == "INVALID_ARGUMENT"
    with pytest.raises(ProposalError) as error:
        store.create(None, {})
    assert error.value.code == "AUTHENTICATION_REQUIRED"


def test_persistent_retry_survives_conversation_expiry(db):
    import json
    from uuid import uuid4

    from test_proposals import PREPARE_HASH, snapshot

    from linescope.proposals import ProposalStore

    db.migrate()
    owner = context()
    now = [0.0]
    conversations = ConversationStore(clock=lambda: now[0])
    identity = conversations.create(owner, {"candidates": []})
    request = parse(
        json.dumps({"message": "設備状態を停止に変更", "context_id": identity}), str(uuid4())
    )
    store = ProposalStore(db)
    saved = store.save(
        owner,
        snapshot(owner),
        request.retry_key,
        prepare_input_hash=PREPARE_HASH,
        agent_input_hash=request.input_hash,
    )
    now[0] = 1800
    with pytest.raises(ProposalError):
        conversations.get(owner, identity)
    # Persistent lookup requires no conversation store and precedes LLM/context work.
    retry = store.find_by_retry(owner, request.retry_key, agent_input_hash=request.input_hash)
    assert retry.update_request_id == saved.update_request_id
    assert retry.replayed
