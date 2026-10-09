from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from linescope.canonical import canonical_hash, canonical_json
from linescope.database import Database
from linescope.execution import ExecutionContext
from linescope.proposals import ProposalError, ProposalStore
from linescope.relations import dependency_relation_create_target
from linescope.settings import Settings
from linescope.snapshot import (
    build_dependency_relation_snapshot,
    build_equipment_state_snapshot,
    build_maintenance_snapshot,
    build_production_operation_snapshot,
    equipment_state_target,
    maintenance_plan_create_target,
    maintenance_plan_target,
    production_operation_target,
)

PREPARE_HASH = canonical_hash(
    {
        "prepare_tool": "prepare_equipment_state_update",
        "input": {"equipment_id": str(UUID(int=1)), "state_code": "STOPPED"},
    }
)
AGENT_HASH = canonical_hash(
    {
        "message": "Stop equipment",
        "explicit_as_of": None,
        "context_id": None,
        "replace_update_request_id": None,
    }
)
NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def context(user="floor1", role="floor"):
    return ExecutionContext(user, role, uuid4())


def snapshot(identity=None, version=1, supersedes=None):
    identity = identity or context()
    return build_equipment_state_snapshot(
        identity,
        [
            equipment_state_target(
                {
                    "equipment_id": str(UUID(int=1)),
                    "state_code": "RUNNING",
                    "version": version,
                },
                "STOPPED",
            )
        ],
        supersedes,
    )


def plan_values():
    return {
        "plan_code": "PLAN1",
        "equipment_id": str(UUID(int=1)),
        "planned_start": NOW,
        "planned_end": NOW + timedelta(hours=1),
        "plan_status": "PLANNED",
    }


def category_snapshot(category, identity):
    if category == "equipment":
        return snapshot(identity)
    if category == "maintenance":
        return build_maintenance_snapshot(identity, [maintenance_plan_create_target(plan_values())])
    if category == "production":
        parent = {
            "production_operation_id": str(UUID(int=2)),
            "operation_code": "OP1",
            "process_id": str(UUID(int=3)),
            "planned_status": "PLANNED",
            "planned_start": NOW,
            "planned_end": NOW + timedelta(hours=1),
            "active": True,
            "version": 1,
        }
        return build_production_operation_snapshot(
            identity, [production_operation_target(parent, {"planned_status": "CANCELLED"})]
        )
    relation = {
        "source_entity_type": "Equipment",
        "source_entity_id": str(UUID(int=1)),
        "target_entity_type": "InfrastructureResource",
        "target_entity_id": str(UUID(int=4)),
        "relation_type": "DEPENDS_ON",
        "effective_from": NOW,
        "effective_to": None,
        "required": True,
        "active": True,
    }
    return build_dependency_relation_snapshot(
        identity, [dependency_relation_create_target(relation)]
    )


@pytest.fixture
def db_store(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'EQ1','Machine','machine',true)",
            (UUID(int=1),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'RUNNING')",
            (UUID(int=1),),
        )
    return db, ProposalStore(db)


def save(store, candidate=None, identity=None, key=None, **changes):
    identity = identity or context()
    return store.save(
        identity,
        candidate or snapshot(identity),
        key or uuid4(),
        **{
            "prepare_input_hash": PREPARE_HASH,
            "agent_input_hash": AGENT_HASH,
            **changes,
        },
    )


def counts(db):
    with db.transaction() as connection:
        return connection.execute(
            "SELECT (SELECT count(*) FROM update_request) AS requests,(SELECT count(*) FROM update_target) AS targets,(SELECT count(*) FROM approval) AS approvals"
        ).fetchone()


def test_save_roundtrip_does_not_update_business_state(db_store):
    db, store = db_store
    candidate, key = snapshot(), uuid4()
    result = save(store, candidate, key=key)
    assert not result.replayed
    assert result.snapshot == candidate
    assert result.status == "WAITING_APPROVAL" and result.approval_status == "PENDING"
    assert result.operation_type == "UPDATE"
    assert all(
        value.version == 4
        for value in [result.update_request_id, result.approval_id, result.idempotency_key]
    )
    assert counts(db) == {"requests": 1, "targets": 1, "approvals": 1}
    with db.transaction() as connection:
        assert connection.execute(
            "SELECT state_code,version FROM equipment_current_state"
        ).fetchone() == {"state_code": "RUNNING", "version": 1}
    reloaded = store.find_by_retry(
        context(), str(key).upper(), prepare_input_hash=PREPARE_HASH, agent_input_hash=AGENT_HASH
    )
    assert reloaded.replayed and reloaded.snapshot == candidate
    assert reloaded.update_request_id == result.update_request_id
    reloaded.snapshot.data["targets"].clear()
    assert store.find_by_retry(context(), key, agent_input_hash=AGENT_HASH).snapshot == candidate


def test_retry_ignores_new_before_version_and_request_id(db_store):
    db, store = db_store
    key = uuid4()
    first = save(store, key=key)
    again = save(store, snapshot(version=100), key=key)
    assert again.replayed and again.snapshot == first.snapshot
    assert again.update_request_id == first.update_request_id
    assert again.approval_id == first.approval_id and again.idempotency_key == first.idempotency_key
    assert counts(db)["requests"] == 1


def test_retry_keeps_original_create_id(db_store):
    _, store = db_store
    identity, key = context("maintenance1", "maintenance"), uuid4()
    first = save(store, category_snapshot("maintenance", identity), identity, key)
    new_candidate = category_snapshot("maintenance", identity)
    assert (
        new_candidate.data["targets"][0]["target_id"]
        != first.snapshot.data["targets"][0]["target_id"]
    )
    again = save(store, new_candidate, identity, key)
    assert again.replayed and again.snapshot == first.snapshot


@pytest.mark.parametrize("field", ["prepare_input_hash", "agent_input_hash"])
def test_retry_content_mismatch_rejected_without_changing_storage(db_store, field):
    db, store = db_store
    key = uuid4()
    first = save(store, key=key)
    with pytest.raises(ProposalError) as caught:
        save(store, key=key, **{field: "0" * 64})
    assert caught.value.code == "DUPLICATE_REQUEST"
    assert (
        store.find_by_retry(context(), key, agent_input_hash=AGENT_HASH).snapshot == first.snapshot
    )
    assert counts(db)["requests"] == 1


def test_retry_key_is_scoped_to_owner_and_owner_can_replay_after_role_change(db_store):
    db, store = db_store
    key = uuid4()
    first = save(store, key=key)
    assert store.find_by_retry(context("other"), key, agent_input_hash=AGENT_HASH) is None
    other = save(store, identity=context("other"), key=key)
    assert other.update_request_id != first.update_request_id
    again = save(store, identity=context(role="production"), key=key)
    assert again.replayed and again.update_request_id == first.update_request_id
    assert counts(db)["requests"] == 2


@pytest.mark.parametrize(
    "category,allowed",
    [
        ("equipment", {"floor", "maintenance", "manager"}),
        ("maintenance", {"maintenance", "manager"}),
        ("production", {"production", "manager"}),
        ("dependency", {"maintenance", "production", "manager"}),
    ],
)
@pytest.mark.parametrize("role", ["floor", "maintenance", "production", "manager"])
def test_request_permissions_for_every_category_and_role(db_store, category, allowed, role):
    db, store = db_store
    identity = context(role=role)
    candidate = category_snapshot(category, identity)
    if role in allowed:
        assert save(store, candidate, identity).snapshot == candidate
    else:
        with pytest.raises(ProposalError) as caught:
            save(store, candidate, identity)
        assert caught.value.code == "AUTHORIZATION_DENIED"
        assert counts(db)["requests"] == 0


def test_mixed_operations_and_multiple_targets_are_saved_in_one_request(db_store):
    db, store = db_store
    identity = context("maintenance1", "maintenance")
    creation = maintenance_plan_create_target(plan_values())
    old = {
        **plan_values(),
        "plan_code": "OLD",
        "maintenance_plan_id": str(UUID(int=9)),
        "version": 2,
    }
    update = maintenance_plan_target(old, {"plan_status": "CANCELLED"})
    candidate = build_maintenance_snapshot(identity, [creation, update])
    result = save(store, candidate, identity)
    assert result.operation_type == "COMPOSITE" and result.snapshot == candidate
    assert counts(db) == {"requests": 1, "targets": 2, "approvals": 1}


def test_failure_on_pending_approval_rolls_back_and_same_key_can_retry(db_store):
    db, store = db_store
    key, candidate = uuid4(), snapshot()
    with db.transaction() as connection:
        connection.execute("""CREATE FUNCTION reject_approval() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='injected failure secret'; END $$;
        CREATE TRIGGER injected_failure BEFORE INSERT ON approval FOR EACH ROW EXECUTE FUNCTION reject_approval();""")
    with pytest.raises(ProposalError) as caught:
        save(store, candidate, key=key)
    assert caught.value.code == "INTERNAL_ERROR" and "secret" not in str(caught.value)
    assert counts(db) == {"requests": 0, "targets": 0, "approvals": 0}
    with db.transaction() as connection:
        connection.execute("DROP TRIGGER injected_failure ON approval")
    assert save(store, candidate, key=key).snapshot == candidate


@pytest.mark.parametrize("different_input", [False, True])
def test_parallel_retry_is_one_bundle_with_original_snapshot(db_store, different_input):
    db, store = db_store
    key, barrier = uuid4(), Barrier(2)

    def submit(index):
        candidate = snapshot(version=index + 1)
        barrier.wait(timeout=5)
        try:
            return save(
                store,
                candidate,
                key=key,
                prepare_input_hash=("0" * 64 if different_input and index else PREPARE_HASH),
            )
        except ProposalError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    successes = [result for result in results if not isinstance(result, ProposalError)]
    if different_input:
        assert len(successes) == 1
        assert [result.code for result in results if isinstance(result, ProposalError)] == [
            "DUPLICATE_REQUEST"
        ]
    else:
        assert successes[0].update_request_id == successes[1].update_request_id
        assert successes[0].snapshot == successes[1].snapshot
        assert sorted(result.replayed for result in successes) == [False, True]
    assert counts(db) == {"requests": 1, "targets": 1, "approvals": 1}


@pytest.mark.parametrize(
    "state,approval_state",
    [
        ("REJECTED", "REJECTED"),
        ("INVALIDATED", "INVALIDATED"),
        ("EXPIRED", "EXPIRED"),
        ("FAILED", "INVALIDATED"),
        ("COMPLETED", "CONSUMED"),
        ("APPROVED", "APPROVED"),
    ],
)
def test_terminal_or_approved_retry_returns_existing_status_without_mutation(
    db_store, state, approval_state
):
    db, store = db_store
    key = uuid4()
    first = save(store, key=key)
    result = Jsonb({"committed": True}) if state == "COMPLETED" else None
    with db.transaction() as connection:
        connection.execute(
            "UPDATE update_request SET status=%s,execution_result=%s", (state, result)
        )
        fields = {
            "status": approval_state,
            "approver": None,
            "approved": None,
            "expires": None,
            "consumed": None,
        }
        if state == "REJECTED":
            fields["approver"] = "maintenance1"
        if state in {"EXPIRED", "COMPLETED", "APPROVED"}:
            fields.update(
                approver="maintenance1", approved=NOW, expires=NOW + timedelta(minutes=30)
            )
        if state == "COMPLETED":
            fields["consumed"] = NOW + timedelta(seconds=1)
        connection.execute(
            "UPDATE approval SET status=%(status)s,approver_id=%(approver)s,approved_at=%(approved)s,expires_at=%(expires)s,consumed_at=%(consumed)s",
            fields,
        )
    again = save(store, snapshot(version=20), key=key)
    assert again.replayed and again.update_request_id == first.update_request_id
    assert again.snapshot == first.snapshot and (again.status, again.approval_status) == (
        state,
        approval_state,
    )


@pytest.mark.parametrize(
    "change",
    [
        "request_hash",
        "approval_hash",
        "target",
        "target_version",
        "missing_target",
        "missing_approval",
        "canonical",
        "requester",
        "state_pair",
        "operation",
    ],
)
def test_stored_corruption_is_rejected_without_repair_or_state_change(db_store, change):
    db, store = db_store
    key = uuid4()
    first = save(store, key=key)
    with db.transaction() as connection:
        if change == "request_hash":
            connection.execute("UPDATE update_request SET snapshot_hash=%s", ("0" * 64,))
        elif change == "approval_hash":
            connection.execute("UPDATE approval SET snapshot_hash=%s", ("0" * 64,))
        elif change == "target":
            after = first.snapshot.data["targets"][0]["after"]
            after["state_code"] = "UNKNOWN"
            connection.execute("UPDATE update_target SET proposed_snapshot=%s", (Jsonb(after),))
        elif change == "target_version":
            connection.execute("UPDATE update_target SET expected_version=2")
        elif change == "missing_target":
            connection.execute("DELETE FROM update_target")
        elif change == "missing_approval":
            connection.execute("DELETE FROM approval")
        elif change in {"canonical", "requester"}:
            payload = first.snapshot.data
            if change == "requester":
                payload["requester_id"] = "other"
            else:
                payload["targets"][0]["after"]["state_code"] = "UNKNOWN"
            digest = canonical_hash(payload)
            connection.execute(
                "UPDATE update_request SET canonical_snapshot=%s,snapshot_hash=%s",
                (canonical_json(payload), digest),
            )
            connection.execute("UPDATE approval SET snapshot_hash=%s", (digest,))
        elif change == "state_pair":
            connection.execute("UPDATE update_request SET status='APPROVED'")
        elif change == "operation":
            connection.execute("UPDATE update_request SET operation_type='COMPOSITE'")
    before = counts(db)
    with pytest.raises(ProposalError) as caught:
        store.find_by_retry(context(), key, agent_input_hash=AGENT_HASH)
    assert caught.value.code == "INTERNAL_ERROR"
    assert counts(db) == before


def test_wrong_requester_invalid_snapshot_and_replacement_do_not_persist(db_store):
    db, store = db_store
    for candidate, expected in [
        (snapshot(context("other")), "AUTHORIZATION_DENIED"),
        ("text", "INVALID_ARGUMENT"),
        (snapshot(supersedes=str(uuid4())), "INVALID_ARGUMENT"),
    ]:
        with pytest.raises(ProposalError) as caught:
            save(store, candidate)
        assert caught.value.code == expected
    assert counts(db)["requests"] == 0


class NoDatabase:
    @contextmanager
    def transaction(self):
        raise AssertionError("Invalid retry arguments must fail before database access")
        yield


@pytest.mark.parametrize(
    "identity,key,prepare_hash,agent_hash,expected",
    [
        ({}, uuid4(), PREPARE_HASH, AGENT_HASH, "AUTHENTICATION_REQUIRED"),
        (context(), "bad", PREPARE_HASH, AGENT_HASH, "INVALID_ARGUMENT"),
        (context(), uuid4(), "BAD", AGENT_HASH, "INVALID_ARGUMENT"),
        (context(), uuid4(), PREPARE_HASH, True, "INVALID_ARGUMENT"),
        (context(), uuid4(), None, None, "INVALID_ARGUMENT"),
    ],
)
def test_invalid_retry_arguments_fail_before_database(
    identity, key, prepare_hash, agent_hash, expected
):
    with pytest.raises(ProposalError) as caught:
        ProposalStore(NoDatabase()).find_by_retry(
            identity, key, prepare_input_hash=prepare_hash, agent_input_hash=agent_hash
        )
    assert caught.value.code == expected


@pytest.mark.parametrize(
    "error,code",
    [
        (psycopg.OperationalError("secret DSN"), "DEPENDENCY_UNAVAILABLE"),
        (psycopg.InterfaceError("secret DSN"), "DEPENDENCY_UNAVAILABLE"),
        (psycopg.errors.LockNotAvailable("secret SQL"), "RESOURCE_BUSY"),
        (psycopg.errors.QueryCanceled("secret SQL"), "RESOURCE_BUSY"),
        (psycopg.errors.CheckViolation("secret SQL"), "INTERNAL_ERROR"),
    ],
)
def test_database_errors_are_sanitized(error, code):
    class Down:
        @contextmanager
        def transaction(self):
            raise error
            yield

    with pytest.raises(ProposalError) as caught:
        ProposalStore(Down()).find_by_retry(context(), uuid4(), agent_input_hash=AGENT_HASH)
    assert caught.value.code == code and "secret" not in str(caught.value)
    assert "secret" not in str(caught.value.as_dict())


def test_real_retry_key_lock_timeout_leaves_no_proposal(db_store):
    db, _ = db_store
    store = ProposalStore(Database(Settings(dsn=db.settings.dsn, lock_ms=40)))
    key, candidate = uuid4(), snapshot()
    with db.connect() as connection:
        connection.execute("BEGIN")
        try:
            connection.execute(
                "INSERT INTO update_request(update_request_id,requester_id,operation_type,status,idempotency_key,prepare_retry_key,prepare_input_hash,agent_input_hash,canonical_snapshot,snapshot_schema_version,snapshot_hash) VALUES(%s,'floor1','UPDATE','WAITING_APPROVAL',%s,%s,%s,%s,%s,1,%s)",
                (
                    uuid4(),
                    uuid4(),
                    key,
                    PREPARE_HASH,
                    AGENT_HASH,
                    candidate.canonical_text,
                    candidate.snapshot_hash,
                ),
            )
            with pytest.raises(ProposalError) as caught:
                save(store, candidate, key=key)
            assert caught.value.code == "RESOURCE_BUSY"
        finally:
            connection.execute("ROLLBACK")
    assert counts(db)["requests"] == 0
