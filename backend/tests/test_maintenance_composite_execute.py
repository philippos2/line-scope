"""Mixed maintenance applies all Targets, history and approval consumption atomically."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import psycopg
import pytest
from test_maintenance_plan_approval_api import act, client_for, current
from test_maintenance_plan_execute import settings
from test_maintenance_prepare import create_plan, create_record, identity, prepare, update
from test_maintenance_prepare import service as maintenance_fixture

from linescope.canonical import normalize_timestamp
from linescope.execute import MaintenanceExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError
from linescope.reads import json_value


@pytest.fixture
def world(db):
    db, service = maintenance_fixture.__wrapped__(db)
    return db, service


def approved(db, service, targets=None):
    saved = prepare(service, targets)
    with client_for(db) as client:
        assert act(client, saved, "approve").status_code == 200
    return saved


def execute(db, saved, actor=None, role="maintenance"):
    return MaintenanceExecute(db, settings(role), EventLogger(stream=io.StringIO())).execute(
        actor or identity(), str(saved.update_request_id)
    )


def business(db):
    with db.transaction() as c:
        result = json_value(
            c.execute(
                "SELECT (SELECT jsonb_agg(to_jsonb(p) ORDER BY maintenance_plan_id) FROM maintenance_plan p) AS plans,"
                "(SELECT jsonb_agg(to_jsonb(r) ORDER BY maintenance_record_id) FROM maintenance_record r) AS records,"
                "(SELECT jsonb_agg(to_jsonb(e) ORDER BY equipment_id) FROM equipment_current_state e) AS equipment,"
                "(SELECT count(*) FROM business_update_history) AS histories"
            ).fetchone()
        )

    for rows, fields in (
        (result["plans"], ("planned_start", "planned_end")),
        (result["records"], ("performed_at",)),
    ):
        for row in rows or []:
            for field in fields:
                row[field] = normalize_timestamp(row[field])
    return result


@pytest.mark.parametrize("kind", ["all", "update_record", "create_record", "update_create"])
def test_each_mixed_request_commits_one_history_and_replays_once(world, kind):
    db, service = world
    targets = {
        "all": None,
        "update_record": [update(), create_record()],
        "create_record": [create_plan(), create_record(plan_id=None)],
        "update_create": [update(), create_plan()],
    }[kind]
    saved = approved(db, service, targets)
    equipment = business(db)["equipment"]
    result = execute(db, saved)
    assert result["targets"] == saved.snapshot.data["targets"]
    assert current(db, saved)["status"] == "COMPLETED"
    assert current(db, saved)["approval_status"] == "CONSUMED"
    after = business(db)
    assert after["equipment"] == equipment and after["histories"] == 1
    for target in result["targets"]:
        rows = after["records"] if target["target_type"] == "MaintenanceRecord" else after["plans"]
        id_field = (
            "maintenance_record_id"
            if target["target_type"] == "MaintenanceRecord"
            else "maintenance_plan_id"
        )
        assert next(row for row in rows if row[id_field] == target["target_id"]) == target["after"]
    with db.transaction() as c:
        history = c.execute("SELECT * FROM business_update_history").fetchone()
        assert history["category"] == "MAINTENANCE"
        assert [t["snapshot"] for t in history["before_snapshot"]["targets"]] == [
            t["before"] for t in result["targets"]
        ]
        assert [t["snapshot"] for t in history["after_snapshot"]["targets"]] == [
            t["after"] for t in result["targets"]
        ]
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='EXECUTE'"
            ).fetchone()["n"]
            == 1
        )
    assert execute(db, saved, role="floor") == result
    assert business(db) == after


@pytest.mark.parametrize("fault", ["version", "missing", "mismatch", "plan_code", "record_code"])
def test_any_conflict_after_approval_leaves_no_partial_changes(world, fault):
    db, service = world
    saved = approved(db, service)
    with db.transaction() as c:
        if fault in {"version", "missing", "mismatch"}:
            query = {
                "version": "UPDATE maintenance_plan SET version=6 WHERE maintenance_plan_id=%s",
                "missing": "DELETE FROM maintenance_plan WHERE maintenance_plan_id=%s",
                "mismatch": "UPDATE maintenance_plan SET equipment_id='00000000-0000-0000-0000-00000000000b' WHERE maintenance_plan_id=%s",
            }[fault]
            c.execute(query, (UUID(int=20),))
        elif fault == "plan_code":
            after = next(
                t["after"]
                for t in saved.snapshot.data["targets"]
                if t["target_type"] == "MaintenancePlan" and t["operation_type"] == "CREATE"
            )
            c.execute(
                "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    UUID(int=100),
                    after["plan_code"],
                    after["equipment_id"],
                    after["planned_start"],
                    after["planned_end"],
                    after["plan_status"],
                ),
            )
        else:
            after = next(
                t["after"]
                for t in saved.snapshot.data["targets"]
                if t["target_type"] == "MaintenanceRecord"
            )
            c.execute(
                "INSERT INTO maintenance_record(maintenance_record_id,record_code,equipment_id,performed_at,result) VALUES(%s,%s,%s,%s,%s)",
                (
                    UUID(int=100),
                    after["record_code"],
                    after["equipment_id"],
                    after["performed_at"],
                    after["result"],
                ),
            )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == (
        "VERSION_CONFLICT" if fault in {"version", "missing", "mismatch"} else "CREATE_CONFLICT"
    )
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert business(db) == before


@pytest.mark.parametrize(
    "table",
    ["maintenance_plan", "maintenance_record", "business_update_history", "update_audit_event"],
)
def test_failure_at_each_write_stage_rolls_back_and_preserves_retry(world, table):
    db, service = world
    saved = approved(db, service)
    before = business(db)
    with db.transaction() as c:
        c.execute("""CREATE FUNCTION fail_mixed_execute() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'private-secret'; END $$""")
        # Fixed pytest table values only; no user-provided SQL identifiers.
        c.execute(
            f"CREATE TRIGGER fail_mixed_execute BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fail_mixed_execute()"
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "APPROVED"
    assert business(db) == before
    with db.transaction() as c:
        c.execute(f"DROP TRIGGER fail_mixed_execute ON {table}")
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]


def test_parallel_same_request_returns_one_durable_result(world):
    db, service = world
    saved = approved(db, service)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: execute(db, saved), range(2)))
    assert results[0] == results[1] and business(db)["histories"] == 1


def test_crossed_update_and_reference_requests_use_compatible_lock_order(world):
    db, service = world
    left = approved(db, service, [update(20), create_record(plan_id=21)])
    record = create_record(plan_id=20)
    record["input"]["record_code"] = "OTHER"
    right = approved(db, service, [update(21), record])
    gate = Barrier(2)

    def run(saved):
        gate.wait(timeout=5)
        return execute(db, saved)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, [left, right]))
    assert results[0]["history_id"] != results[1]["history_id"]
    assert business(db)["histories"] == 2


@pytest.mark.parametrize(
    "actor,role,code",
    [
        (identity(user="other"), "maintenance", "AUTHORIZATION_DENIED"),
        (identity("floor"), "maintenance", "APPROVAL_INVALIDATED"),
        (identity(), "floor", "APPROVAL_INVALIDATED"),
    ],
)
def test_owner_and_current_requester_approver_permissions(world, actor, role, code):
    db, service = world
    saved = approved(db, service)
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved, actor, role)
    assert caught.value.code == code
    assert business(db) == before


@pytest.mark.parametrize("fault", ["mismatch", "missing"])
def test_record_reference_failure_without_plan_update_invalidates_all(world, fault):
    db, service = world
    saved = approved(db, service, [create_plan(), create_record()])
    with db.transaction() as c:
        c.execute(
            "UPDATE maintenance_plan SET equipment_id=%s WHERE maintenance_plan_id=%s"
            if fault == "mismatch"
            else "DELETE FROM maintenance_plan WHERE equipment_id=%s AND maintenance_plan_id=%s",
            (UUID(int=11) if fault == "mismatch" else UUID(int=10), UUID(int=20)),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert business(db) == before


@pytest.mark.parametrize("kind", ["plan", "record"])
def test_create_race_after_validation_rolls_back_losing_whole_request(world, monkeypatch, kind):
    db, service = world
    left = approved(db, service, [create_plan("A"), create_record()])
    record = create_record()
    record["input"]["record_code"] = "OTHER" if kind == "plan" else "RECORD"
    right = approved(db, service, [create_plan("A" if kind == "plan" else "B"), record])
    gate = Barrier(2)
    apply = MaintenanceExecute._apply

    def gated_apply(c, request_id, targets, executed_at):
        gate.wait(timeout=5)
        return apply(c, request_id, targets, executed_at)

    monkeypatch.setattr(MaintenanceExecute, "_apply", staticmethod(gated_apply))

    def run(saved):
        try:
            execute(db, saved)
            return "COMPLETED"
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, [left, right])) == ["COMPLETED", "CREATE_CONFLICT"]
    after = business(db)
    assert len(after["plans"]) == 3 and len(after["records"]) == after["histories"] == 1
    assert sorted(current(db, saved)["status"] for saved in [left, right]) == [
        "COMPLETED",
        "INVALIDATED",
    ]


def test_expired_mixed_request_does_not_apply_any_target(world):
    db, service = world
    saved = approved(db, service)
    with db.transaction() as c:
        c.execute(
            "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',expires_at=statement_timestamp()-interval '1 minute' WHERE approval_id=%s",
            (saved.approval_id,),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED"
    assert business(db) == before


def test_missing_equipment_rejects_all_mixed_targets(world):
    db, service = world
    saved = approved(db, service, [update(), create_record(plan_id=None, equipment_id=11)])
    with db.transaction() as c:
        c.execute("DELETE FROM equipment_current_state WHERE equipment_id=%s", (UUID(int=11),))
        c.execute("DELETE FROM equipment WHERE equipment_id=%s", (UUID(int=11),))
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert business(db) == before


def test_reference_only_plan_cannot_be_reassigned_during_mixed_apply(world, monkeypatch):
    db, service = world
    saved = approved(db, service, [update(), create_record(plan_id=21)])
    apply = MaintenanceExecute._apply

    def check_reference_lock(c, request_id, targets, executed_at):
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with db.transaction() as other:
                other.execute("SET LOCAL lock_timeout='50ms'")
                other.execute(
                    "UPDATE maintenance_plan SET equipment_id=%s WHERE maintenance_plan_id=%s",
                    (UUID(int=11), UUID(int=21)),
                )
        return apply(c, request_id, targets, executed_at)

    monkeypatch.setattr(MaintenanceExecute, "_apply", staticmethod(check_reference_lock))
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]
