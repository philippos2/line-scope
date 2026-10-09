from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest

from linescope.canonical import canonical_hash
from linescope.execution import ExecutionContext
from linescope.prepare import PLAN_CREATE, RECORD_CREATE, MaintenanceCreatePrepare
from linescope.proposals import ProposalError

AGENT_HASH = canonical_hash({"message": "Prepare maintenance", "context_id": None})
START = "2026-10-09T00:00:00.000000Z"
END = "2026-10-10T00:00:00.000000Z"


def identity(role="maintenance", user="maintenance1"):
    return ExecutionContext(user, role, uuid4())


def plan(**changes):
    return {
        "plan_code": "NEW",
        "equipment_id": str(UUID(int=10)),
        "planned_start": START,
        "planned_end": END,
        "plan_status": "PLANNED",
        **changes,
    }


def record(**changes):
    return {
        "record_code": "NEW",
        "equipment_id": str(UUID(int=10)),
        "performed_at": START,
        "result": "  Inspected.\nNo issue.  ",
        **changes,
    }


def target(tool=PLAN_CREATE, values=None):
    return {
        "prepare_tool": tool,
        "input": values if values is not None else plan() if tool == PLAN_CREATE else record(),
    }


@pytest.fixture
def service(db):
    db.migrate()
    with db.transaction() as connection:
        for number in (10, 11):
            connection.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,%s,'Machine','machine',true)",
                (UUID(int=number), f"EQ{number}"),
            )
            connection.execute(
                "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'RUNNING')",
                (UUID(int=number),),
            )
        connection.execute(
            "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status) VALUES(%s,'OLD',%s,%s,%s,'PLANNED')",
            (UUID(int=20), UUID(int=10), START, END),
        )
    return db, MaintenanceCreatePrepare(db)


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


def insert_business(connection, tool, values):
    if tool == PLAN_CREATE:
        connection.execute(
            "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                values["plan_code"],
                values["equipment_id"],
                values["planned_start"],
                values["planned_end"],
                values["plan_status"],
            ),
        )
    else:
        connection.execute(
            "INSERT INTO maintenance_record(maintenance_record_id,record_code,equipment_id,performed_at,result,maintenance_plan_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                values["record_code"],
                values["equipment_id"],
                values["performed_at"],
                values["result"],
                values.get("maintenance_plan_id"),
            ),
        )


def test_mixed_creates_generate_ids_and_have_no_business_side_effects(service):
    db, svc = service
    inputs = [target(RECORD_CREATE, record(maintenance_plan_id=str(UUID(int=20)))), target()]
    original = deepcopy(inputs)
    saved = prepare(svc, inputs)
    assert inputs == original
    assert (saved.status, saved.approval_status, saved.operation_type) == (
        "WAITING_APPROVAL",
        "PENDING",
        "CREATE",
    )
    rows = {row["target_type"]: row for row in saved.snapshot.data["targets"]}
    assert set(rows) == {"MaintenancePlan", "MaintenanceRecord"}
    for kind, row in rows.items():
        assert UUID(row["target_id"]).version == 4
        assert row["operation_type"] == "CREATE"
        assert row["before"] is row["expected_version"] is None
        assert row["after"]["version"] == 1
        field = "maintenance_plan_id" if kind == "MaintenancePlan" else "maintenance_record_id"
        assert row["after"][field] == row["target_id"]
    assert rows["MaintenanceRecord"]["after"]["maintenance_plan_id"] == str(UUID(int=20))
    assert rows["MaintenanceRecord"]["after"]["result"] == original[0]["input"]["result"]
    assert rows["MaintenancePlan"]["after"]["planned_start"] == START
    assert counts(db) == {"requests": 1, "targets": 2, "approvals": 1}
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM maintenance_plan").fetchone()["n"] == 1
        assert (
            connection.execute("SELECT count(*) AS n FROM maintenance_record").fetchone()["n"] == 0
        )
        assert (
            connection.execute("SELECT plan_status FROM maintenance_plan").fetchone()["plan_status"]
            == "PLANNED"
        )
        assert all(
            row["state_code"] == "RUNNING"
            for row in connection.execute("SELECT state_code FROM equipment_current_state")
        )


@pytest.mark.parametrize("tool", [PLAN_CREATE, RECORD_CREATE])
@pytest.mark.parametrize("role", ["maintenance", "manager"])
def test_allowed_roles(service, tool, role):
    assert prepare(service[1], [target(tool)], context=identity(role)).status == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "context,code",
    [
        (identity("floor"), "AUTHORIZATION_DENIED"),
        (identity("production"), "AUTHORIZATION_DENIED"),
        (object(), "AUTHENTICATION_REQUIRED"),
    ],
)
def test_permission_before_database(context, code):
    class NoDatabase:
        def transaction(self):
            pytest.fail("Unauthorized request reached database")

    with pytest.raises(ProposalError) as caught:
        MaintenanceCreatePrepare(NoDatabase()).prepare(
            context, [target()], uuid4(), agent_input_hash=AGENT_HASH
        )
    assert caught.value.code == code


@pytest.mark.parametrize(
    "candidate",
    [
        target(values=plan(version=1)),
        target(values=plan(maintenance_plan_id=str(UUID(int=1)))),
        target(values=plan(planned_start=None)),
        target(values=plan(planned_start="2026-10-09")),
        target(values=plan(plan_status="COMPLETED")),
        target(values=plan(plan_code=3)),
        target(RECORD_CREATE, record(maintenance_record_id=str(UUID(int=1)))),
        target(RECORD_CREATE, record(result="  ")),
        target(RECORD_CREATE, record(result=True)),
        target(RECORD_CREATE, record(performed_at="2026-10-09T00:00:00")),
        target(RECORD_CREATE, record(maintenance_plan_id="bad")),
        target(RECORD_CREATE, record(record_code="\ud800")),
        {"prepare_tool": PLAN_CREATE, "input": {"equipment_id": str(UUID(int=10))}},
        {"prepare_tool": PLAN_CREATE, "input": None},
        {"prepare_tool": "unknown", "input": {}},
    ],
)
def test_invalid_inputs_reject_without_proposal(service, candidate):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [candidate])
    assert caught.value.code == "INVALID_ARGUMENT"
    assert counts(db)["requests"] == 0


@pytest.mark.parametrize(
    "targets,code",
    [
        ([], "INVALID_ARGUMENT"),
        ([target(), target()], "BUSINESS_RULE_VIOLATION"),
        ([target(RECORD_CREATE), target(RECORD_CREATE)], "BUSINESS_RULE_VIOLATION"),
        (
            [target(), target(RECORD_CREATE, record(equipment_id=str(UUID(int=99))))],
            "TARGET_NOT_FOUND",
        ),
        (
            [target(), target(RECORD_CREATE, record(maintenance_plan_id=str(UUID(int=99))))],
            "TARGET_NOT_FOUND",
        ),
        (
            [
                target(),
                target(
                    RECORD_CREATE,
                    record(equipment_id=str(UUID(int=11)), maintenance_plan_id=str(UUID(int=20))),
                ),
            ],
            "BUSINESS_RULE_VIOLATION",
        ),
        ([target(values=plan(planned_start=END))], "BUSINESS_RULE_VIOLATION"),
        (
            [
                target(
                    values=plan(
                        planned_start="2026-10-09T00:00:00-12:00",
                        planned_end="2026-10-09T01:00:00+14:00",
                    )
                )
            ],
            "BUSINESS_RULE_VIOLATION",
        ),
        (
            [target(), {"prepare_tool": "prepare_equipment_state_update", "input": {}}],
            "BUSINESS_RULE_VIOLATION",
        ),
    ],
)
def test_all_target_rejection(service, targets, code):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(svc, targets)
    assert caught.value.code == code
    assert counts(db) == {"requests": 0, "targets": 0, "approvals": 0}


@pytest.mark.parametrize("tool", [PLAN_CREATE, RECORD_CREATE])
def test_existing_business_key_rejected(service, tool):
    db, svc = service
    values = target(tool)["input"]
    with db.transaction() as connection:
        insert_business(connection, tool, values)
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [target(tool)])
    assert caught.value.code == "CREATE_CONFLICT"
    assert counts(db)["requests"] == 0


def test_replay_preserves_ids_before_conflict_checks_and_generates_no_new_ids(service, monkeypatch):
    db, svc = service
    key = uuid4()
    first = prepare(svc, [target(), target(RECORD_CREATE)], key=key)
    with db.transaction() as connection:
        insert_business(connection, PLAN_CREATE, plan())
        insert_business(connection, RECORD_CREATE, record())
        connection.execute("UPDATE update_request SET status='REJECTED'")
        connection.execute("UPDATE approval SET status='REJECTED',approver_id='manager1'")

    def no_id():
        pytest.fail("Replay generated a new CREATE ID")

    monkeypatch.setattr("linescope.snapshot.uuid4", no_id)
    replay = prepare(
        svc,
        [
            target(
                RECORD_CREATE,
                record(
                    equipment_id=UUID(int=10).hex.upper(),
                    performed_at="2026-10-09T09:00:00+09:00",
                    maintenance_plan_id=None,
                ),
            ),
            target(
                values=plan(
                    planned_start="2026-10-09T09:00:00+09:00",
                    planned_end="2026-10-10T09:00:00+09:00",
                )
            ),
        ],
        key=key,
    )
    assert replay.replayed and replay.status == "REJECTED"
    assert replay.snapshot == first.snapshot
    assert replay.update_request_id == first.update_request_id
    assert replay.approval_id == first.approval_id
    assert counts(db)["requests"] == 1


@pytest.mark.parametrize("changed", ["input", "agent", "replacement"])
def test_retry_mismatch(service, changed):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    kwargs = {"key": key}
    if changed == "input":
        kwargs["targets"] = [target(values=plan(plan_status="CANCELLED"))]
    elif changed == "agent":
        kwargs["agent_input_hash"] = canonical_hash({"message": "other"})
    else:
        kwargs["supersedes_update_request_id"] = uuid4()
    with pytest.raises(ProposalError) as caught:
        prepare(svc, **kwargs)
    assert caught.value.code == "DUPLICATE_REQUEST"
    assert counts(db)["requests"] == 1


def test_retry_owner_scope_and_permission_loss(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, key=key)
    second = prepare(svc, key=key, context=identity(user="maintenance2"))
    assert first.update_request_id != second.update_request_id
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, context=identity("floor"))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert counts(db)["requests"] == 2


def test_parallel_same_key_keeps_one_request_and_one_set_of_ids(service):
    db, svc = service
    key = uuid4()
    barrier = Barrier(4)

    def run(_):
        barrier.wait(timeout=10)
        return prepare(svc, [target(), target(RECORD_CREATE)], key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({row.update_request_id for row in results}) == 1
    assert len({row.snapshot.canonical_text for row in results}) == 1
    assert sum(not row.replayed for row in results) == 1
    assert counts(db) == {"requests": 1, "targets": 2, "approvals": 1}


def test_failure_rolls_back_both_creates_and_replacement_then_same_key_retries(service):
    db, svc = service
    old = prepare(svc, [target(RECORD_CREATE)])
    key = uuid4()
    with db.transaction() as connection:
        connection.execute(
            "CREATE FUNCTION fail_approval() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture'; END $$"
        )
        connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON approval FOR EACH ROW EXECUTE FUNCTION fail_approval()"
        )
    with pytest.raises(ProposalError) as caught:
        prepare(
            svc,
            [target(), target(RECORD_CREATE)],
            key=key,
            supersedes_update_request_id=old.update_request_id,
        )
    assert caught.value.code == "INTERNAL_ERROR"
    assert counts(db) == {"requests": 1, "targets": 1, "approvals": 1}
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT status FROM update_request").fetchone()["status"]
            == "WAITING_APPROVAL"
        )
        assert connection.execute("SELECT status FROM approval").fetchone()["status"] == "PENDING"
        connection.execute("DROP TRIGGER fail_insert ON approval")
    new = prepare(
        svc,
        [target(), target(RECORD_CREATE)],
        key=key,
        supersedes_update_request_id=old.update_request_id,
    )
    assert new.snapshot.data["supersedes_update_request_id"] == str(old.update_request_id)
    assert counts(db) == {"requests": 2, "targets": 3, "approvals": 2}
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM update_request WHERE update_request_id=%s",
                (old.update_request_id,),
            ).fetchone()["status"]
            == "INVALIDATED"
        )


def test_reference_and_key_checks_share_single_statement_without_business_locks(service):
    db, _ = service
    statements = []

    class RecordingDatabase:
        @contextmanager
        def transaction(self):
            with db.transaction() as connection:

                class Connection:
                    def execute(self, query, params=None):
                        if query.startswith("SELECT ARRAY"):
                            statements.append(query)
                        return connection.execute(query, params)

                yield Connection()

    prepare(
        MaintenanceCreatePrepare(RecordingDatabase()),
        [target(), target(RECORD_CREATE, record(maintenance_plan_id=str(UUID(int=20))))],
    )
    assert len(statements) == 1
    assert "FOR UPDATE" not in statements[0]
    assert all(
        table in statements[0] for table in ("equipment", "maintenance_plan", "maintenance_record")
    )


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
        prepare(MaintenanceCreatePrepare(FailingDatabase()))
    assert caught.value.code == code
    assert "secret" not in str(caught.value)
    assert counts(db)["requests"] == 0
