from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from test_production_prepare import AGENT_HASH, END, NEW_END, START, counts, identity

from linescope.production_prepare import ProductionPrepare
from linescope.proposals import ProposalError


@pytest.fixture
def service(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO process(process_id,process_code,process_name,active) VALUES(%s,'P','Process',true)",
            (UUID(int=10),),
        )
        for number in (100, 101, 102):
            connection.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,%s,'Machine','machine',true)",
                (UUID(int=number), f"EQ{number}"),
            )
        for number in (20, 21):
            connection.execute(
                "INSERT INTO production_operation(production_operation_id,operation_code,process_id,planned_status,planned_start,planned_end,active,version) VALUES(%s,%s,%s,'PLANNED',%s,%s,true,7)",
                (UUID(int=number), f"OP{number}", UUID(int=10), START, END),
            )
            connection.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,4)",
                (UUID(int=number + 10), UUID(int=number), UUID(int=100), START),
            )
    return db, ProductionPrepare(db)


def target(number=20, equipment=(101,), end=END, start=START, patch=None):
    value = {
        "production_operation_id": str(UUID(int=number)),
        "assignment_replacement": {
            "effective_from": start,
            "effective_to": end,
            "equipment_ids": [str(UUID(int=n)) for n in equipment],
        },
    }
    if patch is not None:
        value["patch"] = patch
    return value


def prepare(svc, targets=None, **kwargs):
    return svc.prepare(
        kwargs.pop("context", identity()),
        targets or [target()],
        kwargs.pop("key", uuid4()),
        agent_input_hash=kwargs.pop("agent_input_hash", AGENT_HASH),
        **kwargs,
    )


def parent(saved, number=20):
    return next(
        row
        for row in saved.snapshot.data["targets"]
        if row["target_type"] == "ProductionOperation" and row["target_id"] == str(UUID(int=number))
    )


def test_bounded_replacement_preserves_outside_and_source(service):
    db, svc = service
    saved = prepare(svc, [target(patch={"planned_status": "CANCELLED"})])
    row = parent(saved)
    assert row["expected_version"] == 7 and row["after"]["version"] == 8
    assert row["after"]["planned_status"] == "CANCELLED"
    assignments = row["after"]["equipment_assignments"]
    assert {(a["equipment_id"], a["effective_from"], a["effective_to"]) for a in assignments} == {
        (str(UUID(int=101)), START, END),
        (str(UUID(int=100)), END, None),
    }
    assert len(row["before"]["equipment_assignments"]) == 1
    diffs = [t for t in saved.snapshot.data["targets"] if t["target_type"] != "ProductionOperation"]
    assert {t["operation_type"] for t in diffs} == {"CREATE", "DISABLE"}
    assert saved.operation_type == "COMPOSITE"
    with db.transaction() as connection:
        assert connection.execute(
            "SELECT version,planned_status FROM production_operation WHERE production_operation_id=%s",
            (UUID(int=20),),
        ).fetchone() == {"version": 7, "planned_status": "PLANNED"}
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM production_operation_equipment_assignment"
            ).fetchone()["n"]
            == 2
        )


def test_empty_unbounded_set_removes_assignments(service):
    saved = prepare(service[1], [target(equipment=(), end=None)])
    assert parent(saved)["after"]["equipment_assignments"] == []
    assert {t["operation_type"] for t in saved.snapshot.data["targets"]} == {"UPDATE", "DISABLE"}


def test_inactive_business_key_is_reused(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,%s,false,9)",
            (UUID(int=40), UUID(int=20), UUID(int=101), START, END),
        )
    saved = prepare(svc)
    reused = next(t for t in saved.snapshot.data["targets"] if t["target_id"] == str(UUID(int=40)))
    assert reused["operation_type"] == "UPDATE" and reused["expected_version"] == 9
    assert reused["after"]["active"] and reused["after"]["version"] == 10


@pytest.mark.parametrize("equipment,end", [((100,), None), ((100,), END)])
def test_assignment_noop_rejects_without_schedule_patch(service, equipment, end):
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [target(equipment=equipment, end=end)])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert counts(service[0])["requests"] == 0


def test_assignment_noop_with_real_schedule_change(service):
    saved = prepare(
        service[1], [target(equipment=(100,), end=None, patch={"planned_end": NEW_END})]
    )
    assert len(saved.snapshot.data["targets"]) == 1
    row = parent(saved)
    assert row["before"]["equipment_assignments"] == row["after"]["equipment_assignments"]
    assert row["after"]["version"] == 8


@pytest.mark.parametrize(
    "change",
    [
        {"effective_to": "missing"},
        {"equipment_ids": ["bad"]},
        {"equipment_ids": None},
        {"equipment_ids": [str(UUID(int=101))] * 2},
        {"version": 1},
    ],
)
def test_invalid_assignment_input(service, change):
    value = target()
    value["assignment_replacement"].update(change)
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [value])
    assert caught.value.code == "INVALID_ARGUMENT"
    assert counts(service[0])["requests"] == 0


def test_missing_explicit_end(service):
    value = target()
    del value["assignment_replacement"]["effective_to"]
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [value])
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "bad",
    [
        target(99),
        target(equipment=(999,)),
        target(end=START),
        target(start=NEW_END),
        target(patch={"planned_status": "PLANNED"}),
    ],
)
def test_all_targets_rejected(service, bad):
    with pytest.raises(ProposalError):
        prepare(service[1], [target(21), bad])
    assert counts(service[0]) == {"requests": 0, "targets": 0, "approvals": 0}


def test_mixed_schedule_assignment_targets_and_parent_versions(service):
    saved = prepare(
        service[1],
        [
            target(21),
            {"production_operation_id": str(UUID(int=20)), "patch": {"planned_end": NEW_END}},
        ],
    )
    assert parent(saved, 20)["after"]["version"] == 8
    assert "equipment_assignments" not in parent(saved, 20)["after"]
    assert parent(saved, 21)["after"]["version"] == 8


def test_replay_normalizes_equipment_order_and_retains_ids(service):
    db, svc = service
    key = uuid4()
    first = prepare(svc, [target(equipment=(102, 101))], key=key)
    value = target(equipment=(101, 102), start="2026-10-09T09:00:00+09:00")
    with db.transaction() as connection:
        connection.execute("DELETE FROM production_operation_equipment_assignment")
        connection.execute("UPDATE production_operation SET version=8,planned_status='CANCELLED'")
    second = prepare(svc, [value], key=key)
    assert (
        second.replayed
        and second.snapshot == first.snapshot
        and second.update_request_id == first.update_request_id
    )
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [target(equipment=(102,))], key=key)
    assert caught.value.code == "DUPLICATE_REQUEST"


def test_schedule_retry_compatible_across_entries(service):
    from linescope.production_prepare import ProductionSchedulePrepare

    db, svc = service
    key = uuid4()
    value = {"production_operation_id": str(UUID(int=20)), "patch": {"planned_status": "CANCELLED"}}
    first = prepare(ProductionSchedulePrepare(db), [value], key=key)
    second = prepare(svc, [value], key=key)
    assert second.replayed and second.snapshot == first.snapshot


def test_concurrent_assignment_prepare_single_snapshot(service):
    _, svc = service
    key = uuid4()
    barrier = Barrier(4)

    def run(_):
        barrier.wait()
        return prepare(svc, key=key)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(run, range(4)))
    assert len({r.update_request_id for r in results}) == 1
    assert len({r.snapshot.canonical_text for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1


def test_global_cycle_rejected_even_outside_target_operations(service):
    db, svc = service
    with db.transaction() as connection:
        for number, source, destination in ((200, 100, 101), (201, 101, 100)):
            connection.execute(
                "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,source_entity_id,target_entity_type,target_entity_id,relation_type,effective_from,effective_to,required,active,version) VALUES(%s,'Equipment',%s,'Equipment',%s,'DEPENDS_ON',%s,NULL,false,true,1)",
                (UUID(int=number), UUID(int=source), UUID(int=destination), START),
            )
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert counts(db)["requests"] == 0


def test_single_statement_contains_all_graph_rows_and_no_lock(service, monkeypatch):
    _, svc = service
    original = svc.store._transaction
    queries = []

    class Recording:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            queries.append(sql)
            return self.connection.execute(sql, params)

    @contextmanager
    def transaction(*, read_only=False):
        with original(read_only=read_only) as connection:
            yield Recording(connection) if read_only else connection

    monkeypatch.setattr(svc.store, "_transaction", transaction)
    prepare(svc)
    read = [q for q in queries if "AS operations" in q]
    assert (
        len(read) == 1
        and "dependency_relation" in read[0]
        and "production_operation_equipment_assignment" in read[0]
    )
    assert "FOR UPDATE" not in read[0]


@pytest.mark.parametrize(
    "error,code",
    [
        (psycopg.errors.QueryCanceled("secret"), "RESOURCE_BUSY"),
        (psycopg.OperationalError("secret"), "DEPENDENCY_UNAVAILABLE"),
    ],
)
def test_assignment_read_error_safe(service, monkeypatch, error, code):
    _, svc = service
    original = svc.store._transaction
    calls = 0

    @contextmanager
    def transaction(*, read_only=False):
        nonlocal calls
        calls += 1
        with original(read_only=read_only) as connection:
            if calls == 2:
                raise error
            yield connection

    monkeypatch.setattr(svc.store, "_transaction", transaction)
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == code and "secret" not in str(caught.value)


@pytest.mark.parametrize("role", ["production", "manager"])
def test_assignment_roles(service, role):
    assert prepare(service[1], context=identity(role)).status == "WAITING_APPROVAL"


@pytest.mark.parametrize("role", ["floor", "maintenance"])
def test_assignment_permission_denied(service, role):
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], context=identity(role))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert counts(service[0])["requests"] == 0


def test_bounded_middle_keeps_both_sides(service):
    saved = prepare(service[1], [target(start=END, end=NEW_END)])
    assignments = parent(saved)["after"]["equipment_assignments"]
    assert {(a["equipment_id"], a["effective_from"], a["effective_to"]) for a in assignments} == {
        (str(UUID(int=100)), START, END),
        (str(UUID(int=101)), END, NEW_END),
        (str(UUID(int=100)), NEW_END, None),
    }
    shortened = next(
        t for t in saved.snapshot.data["targets"] if t["target_id"] == str(UUID(int=30))
    )
    assert shortened["operation_type"] == "UPDATE" and shortened["after"]["version"] == 5


def test_all_diffs_and_unrelated_assignments_reach_final_cycle_validation(service, monkeypatch):
    import linescope.production_prepare as module

    original = module.validate_dependency_cycles
    observed = []

    def validate(relations, assignments):
        observed.append(assignments)
        original(relations, assignments)

    monkeypatch.setattr(module, "validate_dependency_cycles", validate)
    saved = prepare(service[1], [target(20), target(21, equipment=(102,))])
    assert len(observed) == 1
    rows = {row["assignment_id"]: row for row in observed[0]}
    for child in saved.snapshot.data["targets"]:
        if child["target_type"] == "ProductionOperationEquipmentAssignment":
            assert rows[child["target_id"]] == child["after"]
    assert len(rows) == 6


def test_assignment_version_overflow_is_not_saved(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute(
            "UPDATE production_operation_equipment_assignment SET version=9223372036854775807 WHERE assignment_id=%s",
            (UUID(int=30),),
        )
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == "INTERNAL_ERROR" and counts(db)["requests"] == 0


def test_source_overlap_fails_closed(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,1)",
            (UUID(int=40), UUID(int=20), UUID(int=100), END),
        )
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == "INTERNAL_ERROR" and counts(db)["requests"] == 0


def test_multi_parent_replacement_failure_rolls_back_all(service):
    db, svc = service
    old = prepare(svc)
    before = counts(db)
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
            [target(20), target(21)],
            key=key,
            supersedes_update_request_id=old.update_request_id,
        )
    assert caught.value.code == "INTERNAL_ERROR" and counts(db) == before
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT status FROM update_request").fetchone()["status"]
            == "WAITING_APPROVAL"
        )
        assert connection.execute("SELECT status FROM approval").fetchone()["status"] == "PENDING"
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM production_operation_equipment_assignment"
            ).fetchone()["n"]
            == 2
        )
        connection.execute("DROP TRIGGER fail_insert ON approval")
    new = prepare(
        svc, [target(20), target(21)], key=key, supersedes_update_request_id=old.update_request_id
    )
    assert len(new.snapshot.data["targets"]) == 8
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM update_request WHERE update_request_id=%s",
                (old.update_request_id,),
            ).fetchone()["status"]
            == "INVALIDATED"
        )


def test_observed_parent_and_assignments_stay_fixed_after_sql_change(service, monkeypatch):
    db, svc = service
    original = svc.store._transaction
    calls = 0

    @contextmanager
    def transaction(*, read_only=False):
        nonlocal calls
        calls += 1
        with original(read_only=read_only) as connection:
            yield connection
        if calls == 2:
            with db.transaction() as connection:
                connection.execute("UPDATE production_operation SET version=9")
                connection.execute("UPDATE production_operation_equipment_assignment SET version=6")

    monkeypatch.setattr(svc.store, "_transaction", transaction)
    saved = prepare(svc)
    assert parent(saved)["expected_version"] == 7
    assert parent(saved)["before"]["equipment_assignments"][0]["version"] == 4


def test_generated_id_collision_with_unrelated_operation_rejected(service, monkeypatch):
    import linescope.assignments as module

    identifiers = iter([UUID(int=31), UUID(int=200)])
    monkeypatch.setattr(module, "uuid4", lambda: next(identifiers))
    with pytest.raises(ProposalError) as caught:
        prepare(service[1])
    assert caught.value.code == "INTERNAL_ERROR" and counts(service[0])["requests"] == 0
