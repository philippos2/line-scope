"""Schedule-only execution commits all parents and leaves assignments unchanged."""

import io
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from test_production_prepare import identity, prepare, target
from test_production_schedule_approval import action, business, current
from test_production_schedule_approval import world as pending_fixture

from linescope.canonical import normalize_timestamp
from linescope.execute import ProductionScheduleExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError
from linescope.settings import Settings


@pytest.fixture
def world(db):
    db, service, saved = pending_fixture.__wrapped__(db)
    action(db, saved)
    return db, service, saved


def execute(db, saved, actor=None, role="production"):
    settings = Settings(users={"token": {"user_id": "approver", "role": role}})
    return ProductionScheduleExecute(db, settings, EventLogger(stream=io.StringIO())).execute(
        actor or identity(), str(saved.update_request_id)
    )


def test_all_schedules_history_consumption_and_replay(world):
    db, _, saved = world
    assignments = business(db)["assignments"]
    result = execute(db, saved)
    assert result["targets"] == saved.snapshot.data["targets"]
    assert (
        current(db, saved)["status"] == "COMPLETED"
        and current(db, saved)["approval_status"] == "CONSUMED"
    )
    with db.transaction() as c:
        for target in result["targets"]:
            row = c.execute(
                "SELECT * FROM production_operation WHERE production_operation_id=%s",
                (target["target_id"],),
            ).fetchone()
            assert normalize_timestamp(row.pop("updated_at")) == result["executed_at"]
            row.pop("created_at")
            row = {
                **row,
                "production_operation_id": str(row["production_operation_id"]),
                "process_id": str(row["process_id"]),
                "planned_start": normalize_timestamp(row["planned_start"]),
                "planned_end": normalize_timestamp(row["planned_end"]),
            }
            assert row == target["after"]
        history = c.execute("SELECT * FROM business_update_history").fetchone()
        assert history["category"] == "PRODUCTION_OPERATION"
        assert [t["snapshot"] for t in history["after_snapshot"]["targets"]] == [
            t["after"] for t in result["targets"]
        ]
        assert [t["snapshot"] for t in history["before_snapshot"]["targets"]] == [
            t["before"] for t in result["targets"]
        ]
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='EXECUTE'"
            ).fetchone()["n"]
            == 1
        )
    after = business(db)
    assert after["assignments"] == assignments
    assert execute(db, saved, role="floor") == result and business(db) == after


@pytest.mark.parametrize("fault", ["version", "missing", "value"])
def test_one_conflict_after_approval_rejects_entire_request(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        query = {
            "version": "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
            "missing": "DELETE FROM production_operation WHERE production_operation_id=%s",
            "value": "UPDATE production_operation SET planned_status='CANCELLED' WHERE production_operation_id=%s",
        }[fault]
        c.execute(query, (UUID(int=21),))
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert business(db) == before
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "table", ["production_operation", "business_update_history", "update_audit_event"]
)
def test_write_failure_rolls_back_all_then_retry_succeeds(world, table):
    db, _, saved = world
    before = business(db)
    with db.transaction() as c:
        c.execute(
            """CREATE FUNCTION fail_schedule_execute() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF TG_TABLE_NAME!='production_operation' OR NEW.production_operation_id='00000000-0000-0000-0000-000000000015' THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW; END $$"""
            if table == "production_operation"
            else """CREATE FUNCTION fail_schedule_execute() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-secret'; END $$"""
        )
        event = "UPDATE" if table == "production_operation" else "INSERT"
        c.execute(
            f"CREATE TRIGGER fail_schedule_execute BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION fail_schedule_execute()"
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "APPROVED"
    assert business(db) == before
    with db.transaction() as c:
        c.execute(f"DROP TRIGGER fail_schedule_execute ON {table}")
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]


@pytest.mark.parametrize(
    "actor,role,code",
    [
        (identity(user="other"), "production", "AUTHORIZATION_DENIED"),
        (identity("maintenance"), "production", "APPROVAL_INVALIDATED"),
        (identity(), "maintenance", "APPROVAL_INVALIDATED"),
    ],
)
def test_owner_and_current_permissions(world, actor, role, code):
    db, _, saved = world
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved, actor, role)
    assert caught.value.code == code and business(db) == before


def test_expired_approval_applies_no_schedule(world):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',expires_at=statement_timestamp()-interval '1 minute' WHERE approval_id=%s",
            (saved.approval_id,),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED" and business(db) == before


def test_parallel_same_request_replays_once(world):
    db, _, saved = world
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: execute(db, saved), range(2)))
    assert results[0] == results[1]
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1


def test_overlapping_approved_requests_allow_only_one_schedule_update(world):
    db, service, left = world
    right = prepare(service, [target(21), target(20, {"planned_end": "2026-10-11T00:00:00Z"})])
    action(db, right)

    def run(saved):
        try:
            execute(db, saved)
            return "COMPLETED"
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, [left, right])) == ["COMPLETED", "VERSION_CONFLICT"]
    assert sorted(current(db, s)["status"] for s in [left, right]) == ["COMPLETED", "INVALIDATED"]


def test_assignment_aware_request_remains_unsupported(db):
    from test_production_assignment_prepare import prepare as prepare_assignments
    from test_production_assignment_prepare import service as assignment_fixture

    db, service = assignment_fixture.__wrapped__(db)
    saved = prepare_assignments(service)
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INVALID_ARGUMENT" and business(db) == before
