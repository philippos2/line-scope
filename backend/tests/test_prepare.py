from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from linescope.canonical import canonical_hash
from linescope.execution import ExecutionContext
from linescope.prepare import EquipmentStatePrepare
from linescope.proposals import ProposalError

AGENT_HASH = canonical_hash({"message": "Stop equipment", "context_id": None})


def identity(role="floor", user="floor1"):
    return ExecutionContext(user, role, uuid4())


def target(number=1, state="STOPPED"):
    return {"equipment_id": str(UUID(int=number)), "state_code": state}


@pytest.fixture
def service(db):
    db.migrate()
    with db.transaction() as connection:
        for number in (1, 2):
            connection.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,%s,'Machine','machine',true)",
                (UUID(int=number), f"EQ{number}"),
            )
            connection.execute(
                "INSERT INTO equipment_current_state(equipment_id,state_code,version) VALUES(%s,'RUNNING',7)",
                (UUID(int=number),),
            )
    return db, EquipmentStatePrepare(db)


def prepare(service, targets=None, context=None, key=None, **kwargs):
    return service.prepare(
        context or identity(),
        targets if targets is not None else [target()],
        key or uuid4(),
        agent_input_hash=kwargs.pop("agent_input_hash", AGENT_HASH),
        **kwargs,
    )


def counts(db):
    with db.transaction() as connection:
        return connection.execute(
            "SELECT (SELECT count(*) FROM update_request) AS requests,(SELECT count(*) FROM update_target) AS targets,(SELECT count(*) FROM approval) AS approvals"
        ).fetchone()


def test_prepare_records_server_versions_without_mutating_business(service):
    db, svc = service
    saved = prepare(svc, [target(2), target(1)])
    assert (saved.status, saved.approval_status) == ("WAITING_APPROVAL", "PENDING")
    assert saved.replayed is False
    assert counts(db) == {"requests": 1, "targets": 2, "approvals": 1}
    for row in saved.snapshot.data["targets"]:
        assert row["before"]["version"] == row["expected_version"] == 7
        assert row["after"]["version"] == 8
        assert row["before"]["state_code"] == "RUNNING"
        assert row["after"]["state_code"] == "STOPPED"
        assert "updated_at" not in row["before"]
    with db.transaction() as connection:
        assert all(
            row["state_code"] == "RUNNING" and row["version"] == 7
            for row in connection.execute("SELECT * FROM equipment_current_state")
        )


@pytest.mark.parametrize("role", ["floor", "maintenance", "manager"])
def test_authorized_roles(service, role):
    assert prepare(service[1], context=identity(role)).status == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "context,code",
    [(identity("production"), "AUTHORIZATION_DENIED"), (object(), "AUTHENTICATION_REQUIRED")],
)
def test_unauthorized_before_database(context, code):
    class NoDatabase:
        def transaction(self):
            pytest.fail("Unauthorized request reached database")

    with pytest.raises(ProposalError) as caught:
        EquipmentStatePrepare(NoDatabase()).prepare(
            context, [target()], uuid4(), agent_input_hash=AGENT_HASH
        )
    assert caught.value.code == code


@pytest.mark.parametrize(
    "targets,code",
    [
        ([], "INVALID_ARGUMENT"),
        ([{**target(), "expected_version": 7}], "INVALID_ARGUMENT"),
        ([target(state="DEGRADED")], "INVALID_ARGUMENT"),
        ([target(state=None)], "INVALID_ARGUMENT"),
        ([{"equipment_id": "bad", "state_code": "STOPPED"}], "INVALID_ARGUMENT"),
        ([target(), target()], "BUSINESS_RULE_VIOLATION"),
        ([target(), target(99)], "TARGET_NOT_FOUND"),
        ([target(), target(2, "RUNNING")], "BUSINESS_RULE_VIOLATION"),
    ],
)
def test_rejected_whole_request(service, targets, code):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, targets)
    assert caught.value.code == code
    assert counts(db) == {"requests": 0, "targets": 0, "approvals": 0}


def test_missing_state_is_integrity_failure(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute(
            "DELETE FROM equipment_current_state WHERE equipment_id=%s", (UUID(int=1),)
        )
    with pytest.raises(ProposalError, match="missing") as caught:
        prepare(svc)
    assert caught.value.code == "INTERNAL_ERROR"
    assert counts(db)["requests"] == 0


def test_replay_preserves_snapshot_after_current_change_and_terminal_state(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, [target(1), target(2)], key=key)
    with db.transaction() as connection:
        connection.execute("UPDATE equipment_current_state SET state_code='STOPPED',version=8")
        connection.execute("UPDATE update_request SET status='REJECTED'")
        connection.execute("UPDATE approval SET status='REJECTED',approver_id='manager1'")
    replay = prepare(
        svc, [target(2), {**target(), "equipment_id": UUID(int=1).hex.upper()}], key=key
    )
    assert replay.replayed
    assert replay.snapshot == first.snapshot
    assert replay.update_request_id == first.update_request_id
    assert replay.status == "REJECTED"
    assert counts(db)["requests"] == 1


@pytest.mark.parametrize("changed", ["state", "agent", "replacement"])
def test_retry_content_mismatch(service, changed):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    kwargs = {"key": key}
    if changed == "state":
        kwargs["targets"] = [target(state="UNKNOWN")]
    elif changed == "agent":
        kwargs["agent_input_hash"] = canonical_hash({"message": "different"})
    else:
        kwargs["supersedes_update_request_id"] = uuid4()
    with pytest.raises(ProposalError) as caught:
        prepare(svc, **kwargs)
    assert caught.value.code == "DUPLICATE_REQUEST"
    assert counts(db)["requests"] == 1


def test_retry_is_owner_scoped_and_requires_current_permission(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, key=key)
    second = prepare(svc, key=key, context=identity(user="floor2"))
    assert first.update_request_id != second.update_request_id
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, context=identity("production"))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert counts(db)["requests"] == 2


def test_replacement_failure_preserves_old_and_retry_after_rollback(service):
    db, svc = service
    old = prepare(svc)
    key = uuid4()
    with db.transaction() as connection:
        connection.execute(
            "CREATE FUNCTION fail_approval() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test failure'; END $$"
        )
        connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON approval FOR EACH ROW EXECUTE FUNCTION fail_approval()"
        )
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, supersedes_update_request_id=old.update_request_id)
    assert caught.value.code == "INTERNAL_ERROR"
    assert counts(db) == {"requests": 1, "targets": 1, "approvals": 1}
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT status FROM update_request").fetchone()["status"]
            == "WAITING_APPROVAL"
        )
        assert connection.execute("SELECT status FROM approval").fetchone()["status"] == "PENDING"
        connection.execute("DROP TRIGGER fail_insert ON approval")
    new = prepare(svc, key=key, supersedes_update_request_id=old.update_request_id)
    assert new.snapshot.data["supersedes_update_request_id"] == str(old.update_request_id)
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM update_request WHERE update_request_id=%s",
                (old.update_request_id,),
            ).fetchone()["status"]
            == "INVALIDATED"
        )


def test_parallel_same_key_saves_one_proposal(service):
    db, svc = service
    barrier = Barrier(4)
    key = uuid4()

    def run(_):
        barrier.wait(timeout=10)
        return prepare(svc, key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({row.update_request_id for row in results}) == 1
    assert sum(not row.replayed for row in results) == 1
    assert counts(db) == {"requests": 1, "targets": 1, "approvals": 1}


def test_change_after_read_keeps_observed_snapshot_without_business_locks(service):
    db, _ = service

    class ChangingDatabase:
        calls = 0

        @contextmanager
        def transaction(self):
            with db.transaction() as connection:
                yield connection
            self.calls += 1
            # First transaction is retry lookup; second is the business read.
            if self.calls != 2:
                return
            with db.transaction() as writer:
                writer.execute("UPDATE equipment_current_state SET state_code='UNKNOWN',version=9")

    saved = prepare(EquipmentStatePrepare(ChangingDatabase()))
    assert saved.snapshot.data["targets"][0]["expected_version"] == 7
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT version FROM equipment_current_state LIMIT 1").fetchone()[
                "version"
            ]
            == 9
        )


@pytest.mark.parametrize("value", [None, "bad", "A" * 64, 3])
def test_invalid_agent_hash_cannot_replay_saved_request(service, value):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, agent_input_hash=value)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert counts(db)["requests"] == 1


def test_version_overflow_is_integrity_failure(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute("UPDATE equipment_current_state SET version=9223372036854775807")
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == "INTERNAL_ERROR"
    assert counts(db)["requests"] == 0


def test_current_rows_are_read_with_one_statement(service):
    db, _ = service
    statements = []

    class RecordingDatabase:
        @contextmanager
        def transaction(self):
            with db.transaction() as connection:

                class Connection:
                    def execute(self, query, params=None):
                        if "FROM equipment e" in query:
                            statements.append(query)
                        return connection.execute(query, params)

                yield Connection()

    prepare(EquipmentStatePrepare(RecordingDatabase()), [target(1), target(2)])
    assert len(statements) == 1
    assert "FOR UPDATE" not in statements[0]


@pytest.mark.parametrize("code", ["RESOURCE_BUSY", "DEPENDENCY_UNAVAILABLE"])
def test_read_database_failures_are_safe(service, code):
    import psycopg

    db, _ = service

    class FailingDatabase:
        calls = 0

        @contextmanager
        def transaction(self):
            self.calls += 1
            if self.calls == 2:
                if code == "RESOURCE_BUSY":
                    raise psycopg.errors.QueryCanceled("secret query")
                raise psycopg.OperationalError("secret connection")
            with db.transaction() as connection:
                yield connection

    with pytest.raises(ProposalError) as caught:
        prepare(EquipmentStatePrepare(FailingDatabase()))
    assert caught.value.code == code
    assert "secret" not in str(caught.value)
    assert counts(db)["requests"] == 0
