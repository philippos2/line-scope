from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest

from linescope.canonical import canonical_hash
from linescope.execution import ExecutionContext
from linescope.production_prepare import ProductionSchedulePrepare
from linescope.proposals import ProposalError

AGENT_HASH = canonical_hash({"message": "Change production schedule", "context_id": None})
START = "2026-10-09T00:00:00.000000Z"
END = "2026-10-10T00:00:00.000000Z"
NEW_END = "2026-10-11T00:00:00.000000Z"


def identity(role="production", user="production1"):
    return ExecutionContext(user, role, uuid4())


def target(number=20, patch=None):
    return {
        "production_operation_id": str(UUID(int=number)),
        "patch": patch if patch is not None else {"planned_status": "CANCELLED"},
    }


@pytest.fixture
def service(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO process(process_id,process_code,process_name,active) VALUES(%s,'PROCESS','Process',true)",
            (UUID(int=10),),
        )
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'EQ','Machine','machine',true)",
            (UUID(int=100),),
        )
        for number in (20, 21):
            connection.execute(
                "INSERT INTO production_operation(production_operation_id,operation_code,process_id,planned_status,planned_start,planned_end,active,version) VALUES(%s,%s,%s,'PLANNED',%s,%s,true,7)",
                (UUID(int=number), f"OP{number}", UUID(int=10), START, END),
            )
        connection.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,4)",
            (UUID(int=30), UUID(int=20), UUID(int=100), START),
        )
    return db, ProductionSchedulePrepare(db)


def prepare(svc, targets=None, *, context=None, key=None, **kwargs):
    return svc.prepare(
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


def test_full_schedule_snapshots_preserve_immutable_fields_and_business_data(service):
    db, svc = service
    saved = prepare(svc, [target(21), target(20, {"planned_end": NEW_END})])
    assert (saved.status, saved.approval_status, saved.operation_type) == (
        "WAITING_APPROVAL",
        "PENDING",
        "UPDATE",
    )
    assert not saved.replayed
    rows = saved.snapshot.data["targets"]
    assert [row["target_id"] for row in rows] == [str(UUID(int=20)), str(UUID(int=21))]
    first = rows[0]
    assert first["business_key"] == {"operation_code": "OP20"}
    assert first["expected_version"] == first["before"]["version"] == 7
    assert first["before"] == {
        "production_operation_id": str(UUID(int=20)),
        "operation_code": "OP20",
        "process_id": str(UUID(int=10)),
        "planned_status": "PLANNED",
        "planned_start": START,
        "planned_end": END,
        "active": True,
        "version": 7,
    }
    assert first["after"] == {**first["before"], "planned_end": NEW_END, "version": 8}
    assert all(row["target_type"] == "ProductionOperation" for row in rows)
    assert counts(db) == {"requests": 1, "targets": 2, "approvals": 1}
    with db.transaction() as connection:
        for row in connection.execute("SELECT * FROM production_operation"):
            assert row["version"] == 7 and row["planned_status"] == "PLANNED"
            assert row["planned_end"] == datetime(2026, 10, 10, tzinfo=timezone.utc)
        assignment = connection.execute(
            "SELECT * FROM production_operation_equipment_assignment"
        ).fetchone()
        assert (
            assignment["active"]
            and assignment["version"] == 4
            and assignment["effective_to"] is None
        )


@pytest.mark.parametrize("role", ["production", "manager"])
def test_allowed_roles(service, role):
    assert prepare(service[1], context=identity(role)).status == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "context,code",
    [
        (identity("floor"), "AUTHORIZATION_DENIED"),
        (identity("maintenance"), "AUTHORIZATION_DENIED"),
        (object(), "AUTHENTICATION_REQUIRED"),
    ],
)
def test_permission_before_database(context, code):
    class NoDatabase:
        def transaction(self):
            pytest.fail("Unauthorized request reached database")

    with pytest.raises(ProposalError) as caught:
        prepare(ProductionSchedulePrepare(NoDatabase()), context=context)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"version": 10},
        {"operation_code": "OTHER"},
        {"process_id": str(UUID(int=11))},
        {"active": False},
        {"planned_status": "RUNNING"},
        {"planned_status": None},
        {"planned_status": True},
        {"planned_start": None},
        {"planned_start": "2026-10-09T00:00:00"},
        {"planned_start": "2026-10-09T00:00:00.1234567Z"},
    ],
)
def test_invalid_patch_rejected(service, patch):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [target(patch=patch)])
    assert caught.value.code == "INVALID_ARGUMENT"
    assert counts(db)["requests"] == 0


@pytest.mark.parametrize(
    "targets,code",
    [
        ([], "INVALID_ARGUMENT"),
        ([{**target(), "expected_version": 7}], "INVALID_ARGUMENT"),
        (
            [
                {
                    **target(),
                    "assignment_replacement": {
                        "effective_from": START,
                        "effective_to": None,
                        "equipment_ids": [],
                    },
                }
            ],
            "INVALID_ARGUMENT",
        ),
        ([target(), target()], "BUSINESS_RULE_VIOLATION"),
        ([target(), target(99)], "TARGET_NOT_FOUND"),
        ([target(), target(21, {"planned_status": "PLANNED"})], "BUSINESS_RULE_VIOLATION"),
        ([target(), target(21, {"planned_start": END})], "BUSINESS_RULE_VIOLATION"),
        (
            [target(), target(21, {"planned_end": "2026-10-08T00:00:00Z"})],
            "BUSINESS_RULE_VIOLATION",
        ),
    ],
)
def test_whole_request_rejected(service, targets, code):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, targets)
    assert caught.value.code == code
    assert counts(db) == {"requests": 0, "targets": 0, "approvals": 0}


def test_timezone_normalization_and_complete_patch_interval_validation(service):
    _, svc = service
    saved = prepare(
        svc, [target(patch={"planned_start": "2026-10-10T09:00:00+09:00", "planned_end": NEW_END})]
    )
    after = saved.snapshot.data["targets"][0]["after"]
    assert after["planned_start"] == END and after["planned_end"] == NEW_END
    with pytest.raises(ProposalError) as caught:
        prepare(
            svc,
            [
                target(
                    patch={
                        "planned_start": "2026-10-09T00:00:00-12:00",
                        "planned_end": "2026-10-09T01:00:00+14:00",
                    }
                )
            ],
        )
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"


def test_timezone_only_patch_is_noop(service):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [target(patch={"planned_start": "2026-10-09T09:00:00+09:00"})])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert counts(db)["requests"] == 0


def test_cancelled_to_planned_is_allowed(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute("UPDATE production_operation SET planned_status='CANCELLED'")
    saved = prepare(svc, [target(patch={"planned_status": "PLANNED"})])
    assert saved.snapshot.data["targets"][0]["after"]["planned_status"] == "PLANNED"


def test_replay_keeps_observed_snapshot_after_current_change_and_terminal_state(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, [target(), target(21, {"planned_end": NEW_END})], key=key)
    with db.transaction() as connection:
        connection.execute(
            "UPDATE production_operation SET planned_status='CANCELLED',planned_end=%s,version=8",
            (NEW_END,),
        )
        connection.execute("UPDATE update_request SET status='REJECTED'")
        connection.execute("UPDATE approval SET status='REJECTED',approver_id='manager1'")
    alias = target()
    alias["production_operation_id"] = UUID(int=20).hex.upper()
    replay = prepare(
        svc, [target(21, {"planned_end": "2026-10-11T09:00:00+09:00"}), alias], key=key
    )
    assert replay.replayed and replay.status == "REJECTED"
    assert replay.snapshot == first.snapshot
    assert replay.update_request_id == first.update_request_id
    assert counts(db)["requests"] == 1


@pytest.mark.parametrize("mode", ["patch", "agent", "replacement", "explicit_field"])
def test_retry_mismatch(service, mode):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    kwargs = {}
    if mode == "patch":
        kwargs["targets"] = [target(patch={"planned_end": NEW_END})]
    elif mode == "agent":
        kwargs["agent_input_hash"] = canonical_hash({"message": "other"})
    elif mode == "replacement":
        kwargs["supersedes_update_request_id"] = uuid4()
    else:
        kwargs["targets"] = [target(patch={"planned_status": "CANCELLED", "planned_start": START})]
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, **kwargs)
    assert caught.value.code == "DUPLICATE_REQUEST"
    assert counts(db)["requests"] == 1


def test_owner_scope_and_permission_loss(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, key=key)
    second = prepare(svc, key=key, context=identity(user="production2"))
    assert first.update_request_id != second.update_request_id
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, context=identity("maintenance"))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert counts(db)["requests"] == 2


def test_parallel_same_key_saves_one_request(service):
    db, svc = service
    key = uuid4()
    barrier = Barrier(4)

    def run(_):
        barrier.wait(timeout=10)
        return prepare(svc, key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({row.update_request_id for row in results}) == 1
    assert sum(not row.replayed for row in results) == 1
    assert counts(db) == {"requests": 1, "targets": 1, "approvals": 1}


def test_replacement_failure_preserves_old_and_same_key_retries(service):
    db, svc = service
    old = prepare(svc)
    key = uuid4()
    with db.transaction() as connection:
        connection.execute(
            "CREATE FUNCTION fail_approval() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture'; END $$"
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


def test_one_statement_read_preserves_snapshot_and_allows_subsequent_change(service):
    db, _ = service
    statements = []

    class ChangingDatabase:
        calls = 0

        @contextmanager
        def transaction(self):
            with db.transaction() as connection:

                class Connection:
                    def execute(self, query, params=None):
                        if "FROM production_operation " in query:
                            statements.append(query)
                        return connection.execute(query, params)

                yield Connection()
            self.calls += 1
            if self.calls == 2:
                with db.transaction() as writer:
                    writer.execute(
                        "UPDATE production_operation SET version=9,planned_status='CANCELLED'"
                    )

    saved = prepare(ProductionSchedulePrepare(ChangingDatabase()), [target(), target(21)])
    assert len(statements) == 1 and "FOR UPDATE" not in statements[0]
    assert all(row["expected_version"] == 7 for row in saved.snapshot.data["targets"])
    with db.transaction() as connection:
        assert all(
            row["version"] == 9
            for row in connection.execute("SELECT version FROM production_operation")
        )


def test_version_overflow(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute("UPDATE production_operation SET version=9223372036854775807")
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == "INTERNAL_ERROR"
    assert counts(db)["requests"] == 0


@pytest.mark.parametrize("code", ["RESOURCE_BUSY", "DEPENDENCY_UNAVAILABLE"])
def test_read_failures_are_safe(service, code):
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
        prepare(ProductionSchedulePrepare(FailingDatabase()))
    assert caught.value.code == code and "secret" not in str(caught.value)
    assert counts(db)["requests"] == 0
