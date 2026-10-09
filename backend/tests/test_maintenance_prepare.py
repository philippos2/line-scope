from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest

from linescope.canonical import canonical_hash
from linescope.execution import ExecutionContext
from linescope.prepare import (
    PLAN_CREATE,
    PLAN_UPDATE,
    RECORD_CREATE,
    MaintenanceCreatePrepare,
    MaintenancePlanPrepare,
    MaintenancePrepare,
)
from linescope.proposals import ProposalError, ProposalStore
from linescope.snapshot import (
    build_maintenance_snapshot,
    maintenance_plan_target,
    maintenance_record_create_target,
)

AGENT_HASH = canonical_hash({"message": "Update plan and record maintenance", "context_id": None})
START = "2026-10-09T00:00:00.000000Z"
END = "2026-10-10T00:00:00.000000Z"


def identity(role="maintenance", user="maintenance1"):
    return ExecutionContext(user, role, uuid4())


def update(number=20, patch=None):
    return {
        "prepare_tool": PLAN_UPDATE,
        "input": {
            "maintenance_plan_id": str(UUID(int=number)),
            "patch": patch if patch is not None else {"plan_status": "CANCELLED"},
        },
    }


def create_plan(code="NEW"):
    return {
        "prepare_tool": PLAN_CREATE,
        "input": {
            "plan_code": code,
            "equipment_id": str(UUID(int=10)),
            "planned_start": START,
            "planned_end": END,
            "plan_status": "PLANNED",
        },
    }


def create_record(plan_id=20, equipment_id=10):
    return {
        "prepare_tool": RECORD_CREATE,
        "input": {
            "record_code": "RECORD",
            "equipment_id": str(UUID(int=equipment_id)),
            "performed_at": START,
            "result": "Inspected",
            "maintenance_plan_id": str(UUID(int=plan_id)) if plan_id is not None else None,
        },
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
        for number in (20, 21):
            connection.execute(
                "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status,version) VALUES(%s,%s,%s,%s,%s,'PLANNED',5)",
                (UUID(int=number), f"PLAN{number}", UUID(int=10), START, END),
            )
    return db, MaintenancePrepare(db)


def prepare(svc, targets=None, *, key=None, context=None, **kwargs):
    return svc.prepare(
        context or identity(),
        targets if targets is not None else [update(), create_plan(), create_record()],
        key or uuid4(),
        agent_input_hash=AGENT_HASH,
        **kwargs,
    )


def counts(db):
    with db.transaction() as connection:
        return connection.execute(
            "SELECT (SELECT count(*) FROM update_request) AS requests,(SELECT count(*) FROM update_target) AS targets,(SELECT count(*) FROM approval) AS approvals"
        ).fetchone()


def test_three_tools_save_one_composite_request_and_no_business_changes(service):
    db, svc = service
    saved = prepare(svc)
    assert (saved.operation_type, saved.status, saved.approval_status) == (
        "COMPOSITE",
        "WAITING_APPROVAL",
        "PENDING",
    )
    targets = saved.snapshot.data["targets"]
    changed = next(row for row in targets if row["operation_type"] == "UPDATE")
    assert changed["target_id"] == str(UUID(int=20))
    assert changed["expected_version"] == changed["before"]["version"] == 5
    assert changed["after"] == {**changed["before"], "version": 6, "plan_status": "CANCELLED"}
    record = next(row for row in targets if row["target_type"] == "MaintenanceRecord")
    assert record["after"]["maintenance_plan_id"] == changed["target_id"]
    for row in targets:
        if row["operation_type"] == "CREATE":
            assert row["before"] is row["expected_version"] is None
            assert UUID(row["target_id"]).version == 4
            assert row["after"]["version"] == 1
    assert counts(db) == {"requests": 1, "targets": 3, "approvals": 1}
    with db.transaction() as connection:
        assert all(
            row["plan_status"] == "PLANNED" and row["version"] == 5
            for row in connection.execute("SELECT plan_status,version FROM maintenance_plan")
        )
        assert (
            connection.execute("SELECT count(*) AS n FROM maintenance_record").fetchone()["n"] == 0
        )
        assert all(
            row["state_code"] == "RUNNING"
            for row in connection.execute("SELECT state_code FROM equipment_current_state")
        )


@pytest.mark.parametrize("role", ["maintenance", "manager"])
def test_mixed_roles(service, role):
    assert prepare(service[1], context=identity(role)).status == "WAITING_APPROVAL"


@pytest.mark.parametrize("role", ["floor", "production"])
def test_mixed_permission_rejected_before_database(role):
    class NoDatabase:
        def transaction(self):
            pytest.fail("Unauthorized request reached database")

    with pytest.raises(ProposalError) as caught:
        prepare(MaintenancePrepare(NoDatabase()), context=identity(role))
    assert caught.value.code == "AUTHORIZATION_DENIED"


@pytest.mark.parametrize(
    "bad,code",
    [
        (update(99), "TARGET_NOT_FOUND"),
        (update(patch={"plan_status": "PLANNED"}), "BUSINESS_RULE_VIOLATION"),
        (update(patch={"planned_start": END}), "BUSINESS_RULE_VIOLATION"),
        (update(patch={"equipment_id": str(UUID(int=11))}), "INVALID_ARGUMENT"),
        (create_record(equipment_id=11), "BUSINESS_RULE_VIOLATION"),
        (create_record(plan_id=99), "TARGET_NOT_FOUND"),
        (create_plan("PLAN20"), "CREATE_CONFLICT"),
        (
            {"prepare_tool": "prepare_equipment_state_update", "input": {}},
            "BUSINESS_RULE_VIOLATION",
        ),
    ],
)
def test_one_bad_target_rejects_whole_mixed_request(service, bad, code):
    db, svc = service
    with pytest.raises(ProposalError) as caught:
        prepare(
            svc,
            [create_plan(), create_record(), bad]
            if bad["prepare_tool"] == PLAN_UPDATE
            else [update(), bad],
        )
    assert caught.value.code == code
    assert counts(db) == {"requests": 0, "targets": 0, "approvals": 0}


def test_duplicate_update_id_normalized_and_rejected(service):
    db, svc = service
    alias = update()
    alias["input"]["maintenance_plan_id"] = UUID(int=20).hex.upper()
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [update(), alias, create_record()])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert counts(db)["requests"] == 0


def test_invalid_update_generates_no_create_ids(service, monkeypatch):
    db, svc = service

    def no_id():
        pytest.fail("CREATE ID generated before UPDATE validation")

    monkeypatch.setattr("linescope.snapshot.uuid4", no_id)
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [create_plan(), create_record(), update(patch={"plan_status": "PLANNED"})])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert counts(db)["requests"] == 0


def test_mixed_retry_normalizes_order_uuid_timezone_and_keeps_old_snapshot(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, key=key)
    with db.transaction() as connection:
        connection.execute("UPDATE maintenance_plan SET plan_status='CANCELLED',version=6")
    reordered = [create_record(), create_plan(), update()]
    reordered[0]["input"]["maintenance_plan_id"] = UUID(int=20).hex.upper()
    reordered[0]["input"]["performed_at"] = "2026-10-09T09:00:00+09:00"
    replay = prepare(svc, reordered, key=key)
    assert replay.replayed and replay.snapshot == first.snapshot
    assert replay.update_request_id == first.update_request_id
    assert counts(db)["requests"] == 1


@pytest.mark.parametrize("mode", ["update", "record", "omit_update", "replacement"])
def test_mixed_retry_content_mismatch(service, mode):
    db, svc = service
    key = uuid4()
    prepare(svc, key=key)
    targets = [update(), create_plan(), create_record()]
    kwargs = {}
    if mode == "update":
        targets[0] = update(patch={"planned_end": "2026-10-11T00:00:00Z"})
    elif mode == "record":
        targets[2]["input"]["result"] = "Other"
    elif mode == "omit_update":
        targets.pop(0)
    else:
        kwargs["supersedes_update_request_id"] = uuid4()
    with pytest.raises(ProposalError) as caught:
        prepare(svc, targets, key=key, **kwargs)
    assert caught.value.code == "DUPLICATE_REQUEST"
    assert counts(db)["requests"] == 1


@pytest.mark.parametrize("mode", ["update", "create"])
def test_saved_pre_unification_hash_replays_through_both_entrypoints(service, mode):
    db, svc = service
    context, key = identity(), uuid4()
    if mode == "update":
        raw = update()["input"]
        with db.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM maintenance_plan WHERE maintenance_plan_id=%s", (UUID(int=20),)
            ).fetchone()
        proposal_target = maintenance_plan_target(row, raw["patch"])
        # Exact persisted format used before this refactor.
        old_hash = canonical_hash(
            {"prepare_tool": PLAN_UPDATE, "targets": [raw], "supersedes_update_request_id": None}
        )
        inputs = [update()]
        wrapper = MaintenancePlanPrepare(db)
        wrapper_inputs = [raw]
    else:
        inputs = [create_record(plan_id=None)]
        proposal_target = maintenance_record_create_target(inputs[0]["input"])
        old_hash = canonical_hash({"targets": inputs, "supersedes_update_request_id": None})
        wrapper = MaintenanceCreatePrepare(db)
        wrapper_inputs = inputs
    snapshot = build_maintenance_snapshot(context, [proposal_target])
    old = ProposalStore(db).save(
        context, snapshot, key, prepare_input_hash=old_hash, agent_input_hash=AGENT_HASH
    )
    with db.transaction() as connection:
        connection.execute("UPDATE maintenance_plan SET version=9,plan_status='CANCELLED'")
    current = prepare(svc, inputs, context=context, key=key)
    legacy = prepare(wrapper, wrapper_inputs, context=context, key=key)
    assert current.replayed and legacy.replayed
    assert current.snapshot == legacy.snapshot == old.snapshot
    assert current.update_request_id == legacy.update_request_id == old.update_request_id
    assert counts(db)["requests"] == 1


def test_single_statement_observation_covers_update_and_linked_record_then_allows_change(service):
    db, _ = service
    statements = []

    class ChangingDatabase:
        calls = 0

        @contextmanager
        def transaction(self):
            with db.transaction() as connection:

                class Connection:
                    def execute(self, query, params=None):
                        if query.startswith("SELECT ARRAY"):
                            statements.append(query)
                        return connection.execute(query, params)

                yield Connection()
            self.calls += 1
            if self.calls == 2:
                with db.transaction() as writer:
                    writer.execute(
                        "UPDATE maintenance_plan SET equipment_id=%s,version=9 WHERE maintenance_plan_id=%s",
                        (UUID(int=11), UUID(int=20)),
                    )

    saved = prepare(MaintenancePrepare(ChangingDatabase()))
    changed = next(
        row for row in saved.snapshot.data["targets"] if row["operation_type"] == "UPDATE"
    )
    assert changed["expected_version"] == 5
    assert changed["before"]["equipment_id"] == str(UUID(int=10))
    assert len(statements) == 1 and "FOR UPDATE" not in statements[0]
    with db.transaction() as connection:
        assert connection.execute(
            "SELECT equipment_id FROM maintenance_plan WHERE maintenance_plan_id=%s",
            (UUID(int=20),),
        ).fetchone()["equipment_id"] == UUID(int=11)


def test_parallel_mixed_retry_returns_one_composite_request(service):
    db, svc = service
    key = uuid4()
    barrier = Barrier(4)

    def run(_):
        barrier.wait(timeout=10)
        return prepare(svc, key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({row.update_request_id for row in results}) == 1
    assert len({row.snapshot.canonical_text for row in results}) == 1
    assert sum(not row.replayed for row in results) == 1
    assert counts(db) == {"requests": 1, "targets": 3, "approvals": 1}


def test_mixed_replacement_save_failure_rolls_back_all_and_retry_succeeds(service):
    db, svc = service
    old = prepare(svc, [create_record()])
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
    assert new.operation_type == "COMPOSITE"
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM update_request WHERE update_request_id=%s",
                (old.update_request_id,),
            ).fetchone()["status"]
            == "INVALIDATED"
        )
    assert counts(db) == {"requests": 2, "targets": 4, "approvals": 2}


@pytest.mark.parametrize("code", ["RESOURCE_BUSY", "DEPENDENCY_UNAVAILABLE"])
def test_mixed_read_failure_safe_errors(service, code):
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
        prepare(MaintenancePrepare(FailingDatabase()))
    assert caught.value.code == code and "secret" not in str(caught.value)
    assert counts(db)["requests"] == 0
