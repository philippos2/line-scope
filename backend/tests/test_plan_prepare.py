from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest

from linescope.canonical import canonical_hash
from linescope.execution import ExecutionContext
from linescope.prepare import EquipmentStatePrepare, MaintenancePlanPrepare
from linescope.proposals import ProposalError

AGENT_HASH = canonical_hash({"message": "Change maintenance plan", "context_id": None})
START = "2026-10-09T00:00:00.000000Z"
END = "2026-10-10T00:00:00.000000Z"
NEW_END = "2026-10-11T00:00:00.000000Z"


def identity(role="maintenance", user="maintenance1"):
    return ExecutionContext(user, role, uuid4())


def target(number=1, patch=None):
    return {
        "maintenance_plan_id": str(UUID(int=number)),
        "patch": patch if patch is not None else {"plan_status": "CANCELLED"},
    }


@pytest.fixture
def service(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'EQ1','Machine','machine',true)",
            (UUID(int=10),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'RUNNING')",
            (UUID(int=10),),
        )
        for number in (1, 2):
            connection.execute(
                "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status,version) VALUES(%s,%s,%s,%s,%s,'PLANNED',3)",
                (UUID(int=number), f"PLAN{number}", UUID(int=10), START, END),
            )
    return db, MaintenancePlanPrepare(db)


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


def test_multiple_plans_preserve_full_business_values_and_do_not_update_business(service):
    db, svc = service
    saved = prepare(svc, [target(2), target(1, {"planned_end": NEW_END})])
    assert (saved.status, saved.approval_status) == ("WAITING_APPROVAL", "PENDING")
    assert saved.operation_type == "UPDATE"
    assert not saved.replayed
    rows = saved.snapshot.data["targets"]
    assert [row["target_id"] for row in rows] == [str(UUID(int=1)), str(UUID(int=2))]
    first = rows[0]
    assert first["expected_version"] == first["before"]["version"] == 3
    assert first["business_key"] == {"plan_code": "PLAN1"}
    assert first["before"] == {
        "maintenance_plan_id": str(UUID(int=1)),
        "plan_code": "PLAN1",
        "equipment_id": str(UUID(int=10)),
        "planned_start": START,
        "planned_end": END,
        "plan_status": "PLANNED",
        "version": 3,
    }
    assert first["after"] == {**first["before"], "planned_end": NEW_END, "version": 4}
    assert rows[1]["after"]["plan_status"] == "CANCELLED"
    assert counts(db) == {"requests": 1, "targets": 2, "approvals": 1}
    with db.transaction() as connection:
        for row in connection.execute("SELECT * FROM maintenance_plan"):
            assert row["version"] == 3 and row["plan_status"] == "PLANNED"
            assert row["planned_end"] == datetime(2026, 10, 10, tzinfo=timezone.utc)
        assert (
            connection.execute("SELECT state_code FROM equipment_current_state").fetchone()[
                "state_code"
            ]
            == "RUNNING"
        )


@pytest.mark.parametrize("role", ["maintenance", "manager"])
def test_allowed_roles(service, role):
    assert prepare(service[1], context=identity(role)).status == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "context,code",
    [
        (identity("floor"), "AUTHORIZATION_DENIED"),
        (identity("production"), "AUTHORIZATION_DENIED"),
        (object(), "AUTHENTICATION_REQUIRED"),
    ],
)
def test_permission_checked_before_database(context, code):
    class NoDatabase:
        def transaction(self):
            pytest.fail("Unauthorized request reached database")

    with pytest.raises(ProposalError) as caught:
        MaintenancePlanPrepare(NoDatabase()).prepare(
            context, [target()], uuid4(), agent_input_hash=AGENT_HASH
        )
    assert caught.value.code == code


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"equipment_id": str(UUID(int=11))},
        {"plan_code": "OTHER"},
        {"version": 10},
        {"planned_start": None},
        {"planned_start": "2026-10-09T00:00:00"},
        {"planned_start": "2026-10-09T00:00:00.1234567Z"},
        {"plan_status": "COMPLETED"},
        {"plan_status": True},
    ],
)
def test_invalid_patch_is_rejected_before_save(service, patch):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [target(patch=patch)])
    assert caught.value.code == "INVALID_ARGUMENT"
    assert counts(db)["requests"] == 0


@pytest.mark.parametrize(
    "targets,code",
    [
        ([], "INVALID_ARGUMENT"),
        ([{**target(), "expected_version": 3}], "INVALID_ARGUMENT"),
        (
            [{"maintenance_plan_id": "bad", "patch": {"plan_status": "CANCELLED"}}],
            "INVALID_ARGUMENT",
        ),
        ([target(), target()], "BUSINESS_RULE_VIOLATION"),
        ([target(), target(99)], "TARGET_NOT_FOUND"),
        ([target(), target(2, {"plan_status": "PLANNED"})], "BUSINESS_RULE_VIOLATION"),
        ([target(), target(2, {"planned_start": END})], "BUSINESS_RULE_VIOLATION"),
        ([target(), target(2, {"planned_end": "2026-10-08T00:00:00Z"})], "BUSINESS_RULE_VIOLATION"),
    ],
)
def test_invalid_target_rejects_entire_request(service, targets, code):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, targets)
    assert caught.value.code == code
    assert counts(db) == {"requests": 0, "targets": 0, "approvals": 0}


def test_timezone_normalization_before_interval_validation(service):
    # Lexical local time start is before end, but UTC start is later.
    db, svc = service
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
    assert counts(db)["requests"] == 0


def test_timezone_only_patch_is_not_a_business_change(service):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [target(patch={"planned_start": "2026-10-09T09:00:00+09:00"})])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert counts(db)["requests"] == 0


def test_retry_equivalent_uuid_timezone_order_and_changed_current_values(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, [target(2), target(1, {"planned_end": NEW_END})], key=key)
    with db.transaction() as connection:
        connection.execute(
            "UPDATE maintenance_plan SET planned_end=%s,plan_status='CANCELLED',version=4",
            (NEW_END,),
        )
        connection.execute("UPDATE update_request SET status='REJECTED'")
        connection.execute("UPDATE approval SET status='REJECTED',approver_id='manager1'")
    replay = prepare(
        svc,
        [
            {
                "maintenance_plan_id": UUID(int=1).hex.upper(),
                "patch": {"planned_end": "2026-10-11T09:00:00+09:00"},
            },
            target(2),
        ],
        key=key,
    )
    assert replay.replayed and replay.snapshot == first.snapshot
    assert replay.update_request_id == first.update_request_id
    assert replay.approval_id == first.approval_id
    assert replay.status == "REJECTED"
    assert counts(db)["requests"] == 1


@pytest.mark.parametrize("changed", ["patch", "agent", "replacement", "explicit_field"])
def test_retry_mismatch(service, changed):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    kwargs = {"key": key}
    if changed == "patch":
        kwargs["targets"] = [target(patch={"planned_end": NEW_END})]
    elif changed == "agent":
        kwargs["agent_input_hash"] = canonical_hash({"message": "other"})
    elif changed == "replacement":
        kwargs["supersedes_update_request_id"] = uuid4()
    else:
        # Same after value, but different explicit proposal content.
        kwargs["targets"] = [target(patch={"plan_status": "CANCELLED", "planned_start": START})]
    with pytest.raises(ProposalError) as caught:
        prepare(svc, **kwargs)
    assert caught.value.code == "DUPLICATE_REQUEST"
    assert counts(db)["requests"] == 1


def test_retry_cannot_cross_category(service):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    with pytest.raises(ProposalError) as caught:
        EquipmentStatePrepare(db).prepare(
            identity(),
            [{"equipment_id": str(UUID(int=10)), "state_code": "STOPPED"}],
            key,
            agent_input_hash=AGENT_HASH,
        )
    assert caught.value.code == "DUPLICATE_REQUEST"
    assert counts(db)["requests"] == 1


def test_retry_owner_scope_and_lost_permission(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, key=key)
    second = prepare(svc, key=key, context=identity(user="maintenance2"))
    assert first.update_request_id != second.update_request_id
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, context=identity("floor"))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert counts(db)["requests"] == 2


def test_replace_failure_rolls_back_and_same_key_can_retry(service):
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


def test_parallel_same_key_saves_one_request(service):
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


def test_one_statement_read_preserves_observed_version_after_current_change(service):
    db, _ = service
    statements = []

    class ChangingDatabase:
        calls = 0

        @contextmanager
        def transaction(self):
            with db.transaction() as connection:

                class Connection:
                    def execute(self, query, params=None):
                        if "FROM maintenance_plan WHERE" in query:
                            statements.append(query)
                        return connection.execute(query, params)

                yield Connection()
            self.calls += 1
            if self.calls == 2:
                with db.transaction() as writer:
                    writer.execute(
                        "UPDATE maintenance_plan SET planned_end=%s,version=9", (NEW_END,)
                    )

    saved = prepare(MaintenancePlanPrepare(ChangingDatabase()), [target(1), target(2)])
    assert len(statements) == 1 and "FOR UPDATE" not in statements[0]
    assert all(row["expected_version"] == 3 for row in saved.snapshot.data["targets"])
    with db.transaction() as connection:
        assert all(
            row["version"] == 9
            for row in connection.execute("SELECT version FROM maintenance_plan")
        )


def test_version_overflow(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute("UPDATE maintenance_plan SET version=9223372036854775807")
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == "INTERNAL_ERROR"
    assert counts(db)["requests"] == 0


@pytest.mark.parametrize("code", ["RESOURCE_BUSY", "DEPENDENCY_UNAVAILABLE"])
def test_read_failure_safe_errors(service, code):
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
        prepare(MaintenancePlanPrepare(FailingDatabase()))
    assert caught.value.code == code
    assert "secret" not in str(caught.value)
    assert counts(db)["requests"] == 0


def test_start_and_end_are_validated_after_applying_complete_patch(service):
    _, svc = service
    saved = prepare(svc, [target(patch={"planned_start": END, "planned_end": NEW_END})])
    after = saved.snapshot.data["targets"][0]["after"]
    assert after["planned_start"] == END and after["planned_end"] == NEW_END


@pytest.mark.parametrize("value", [None, "bad", "A" * 64])
def test_invalid_agent_hash_cannot_replay(service, value):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, agent_input_hash=value)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert counts(db)["requests"] == 1
