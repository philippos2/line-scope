"""Internal CREATE transaction, including races after uniqueness observation."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from uuid import UUID

import pytest
from test_maintenance_plan_create_approval import approve, current, insert_conflict
from test_maintenance_plan_create_approval import prepared as create_prepared
from test_maintenance_plan_execute import settings
from test_maintenance_prepare import create_plan, identity, prepare, update

from linescope.execute import MaintenancePlanCreateExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError


@pytest.fixture
def approved(db):
    db, service, saved = create_prepared.__wrapped__(db)
    approve(db, saved)
    return db, service, saved


def execute(db, saved, *, actor=None, role="maintenance"):
    return MaintenancePlanCreateExecute(
        db, settings(role), EventLogger(stream=io.StringIO())
    ).execute(actor or identity(), str(saved.update_request_id))


def count(db, table):
    assert table in {"maintenance_plan", "business_update_history", "equipment_state_history"}
    with db.transaction() as connection:
        return connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_create_all_fixed_ids_history_and_replay_without_second_insert(approved):
    db, _, saved = approved
    result = execute(db, saved)
    assert result["targets"] == saved.snapshot.data["targets"]
    assert count(db, "maintenance_plan") == 4
    with db.transaction() as connection:
        for target in result["targets"]:
            plan = connection.execute(
                "SELECT * FROM maintenance_plan WHERE maintenance_plan_id=%s",
                (target["target_id"],),
            ).fetchone()
            assert plan["version"] == 1 and plan["plan_code"] == target["after"]["plan_code"]
        history = connection.execute("SELECT * FROM business_update_history").fetchone()
        assert history["category"] == "MAINTENANCE"
        assert all(t["snapshot"] is None for t in history["before_snapshot"]["targets"])
        assert [t["snapshot"] for t in history["after_snapshot"]["targets"]] == [
            t["after"] for t in result["targets"]
        ]
    assert current(db, saved)["status"] == "COMPLETED"
    assert current(db, saved)["approval_status"] == "CONSUMED"
    assert execute(db, saved, role="floor") == result
    assert count(db, "maintenance_plan") == 4 and count(db, "business_update_history") == 1
    assert count(db, "equipment_state_history") == 0


@pytest.mark.parametrize("id_conflict", [False, True])
def test_post_approval_collision_invalidates_without_any_create(approved, id_conflict):
    db, _, saved = approved
    insert_conflict(db, saved, id_conflict=id_conflict)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "CREATE_CONFLICT"
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert count(db, "maintenance_plan") == 3 and count(db, "business_update_history") == 0


def test_missing_equipment_reference_invalidates_entire_request(approved):
    db, service, _ = approved
    inputs = [create_plan("MISSING-A"), create_plan("MISSING-B")]
    for item in inputs:
        item["input"]["equipment_id"] = str(UUID(int=11))
    saved = prepare(service, inputs)
    approve(db, saved)
    with db.transaction() as connection:
        connection.execute(
            "DELETE FROM equipment_current_state WHERE equipment_id=%s", (UUID(int=11),)
        )
        connection.execute("DELETE FROM equipment WHERE equipment_id=%s", (UUID(int=11),))
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert count(db, "maintenance_plan") == 2 and count(db, "business_update_history") == 0


@pytest.mark.parametrize("failure", ["second_insert", "audit", "suppressed_insert"])
def test_technical_failure_rolls_back_all_rows_and_allows_retry(approved, failure):
    db, _, saved = approved
    with db.transaction() as connection:
        if failure == "audit":
            connection.execute("""CREATE FUNCTION fail_create() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.action='EXECUTE' THEN RAISE EXCEPTION 'private-secret'; END IF;
                RETURN NEW; END $$""")
            table = "update_audit_event"
        elif failure == "suppressed_insert":
            connection.execute("""CREATE FUNCTION fail_create() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RETURN NULL; END $$""")
            table = "maintenance_plan"
        else:
            code = max(t["after"]["plan_code"] for t in saved.snapshot.data["targets"])
            connection.execute("""CREATE FUNCTION fail_create() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.plan_code=TG_ARGV[0] THEN RAISE EXCEPTION 'private-secret'; END IF;
                RETURN NEW; END $$""")
            table = "maintenance_plan"
        # All SQL identifiers and trigger arguments below are fixed test fixture values.
        argument = f"'{code}'" if failure == "second_insert" else ""
        connection.execute(
            f"CREATE TRIGGER fail_create BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fail_create({argument})"
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "APPROVED"
    assert count(db, "maintenance_plan") == 2 and count(db, "business_update_history") == 0
    with db.transaction() as connection:
        connection.execute(f"DROP TRIGGER fail_create ON {table}")
    assert execute(db, saved)["history_id"]
    assert count(db, "maintenance_plan") == 4


def test_parallel_replay_updates_once(approved):
    db, _, saved = approved
    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(lambda _: execute(db, saved), range(2))
    assert first == second
    assert count(db, "maintenance_plan") == 4 and count(db, "business_update_history") == 1


@pytest.mark.parametrize("target_count", [1, 2])
def test_concurrent_requests_hit_unique_constraint_after_both_prechecks(
    approved, target_count, monkeypatch
):
    from linescope import execute as module

    db, service, _ = approved
    inputs = [create_plan(f"RACE-{n}") for n in range(target_count)]
    requests = [prepare(service, inputs), prepare(service, list(reversed(inputs)))]
    for saved in requests:
        approve(db, saved)
    barrier = Barrier(2)

    first_insert = local()
    original_insert = module.insert_maintenance_plan

    def synchronized_insert(connection, after):
        if not getattr(first_insert, "waited", False):
            first_insert.waited = True
            barrier.wait(timeout=10)
        return original_insert(connection, after)

    monkeypatch.setattr(module, "insert_maintenance_plan", synchronized_insert)

    def attempt(saved):
        try:
            return execute(db, saved)["history_id"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, requests))
    assert results.count("CREATE_CONFLICT") == 1
    assert sorted(current(db, saved)["status"] for saved in requests) == [
        "COMPLETED",
        "INVALIDATED",
    ]
    assert (
        count(db, "maintenance_plan") == 2 + target_count
        and count(db, "business_update_history") == 1
    )


@pytest.mark.parametrize(
    "actor,role,code",
    [
        (identity("manager", "other"), "maintenance", "AUTHORIZATION_DENIED"),
        (identity("floor"), "maintenance", "APPROVAL_INVALIDATED"),
        (identity(), "floor", "APPROVAL_INVALIDATED"),
    ],
)
def test_owner_and_current_permission_checks(approved, actor, role, code):
    db, _, saved = approved
    with pytest.raises(ProposalError) as caught:
        execute(db, saved, actor=actor, role=role)
    assert caught.value.code == code
    assert current(db, saved)["status"] == (
        "APPROVED" if code == "AUTHORIZATION_DENIED" else "INVALIDATED"
    )
    assert count(db, "maintenance_plan") == 2


def test_expired_approval_does_not_insert(approved):
    db, _, saved = approved
    with db.transaction() as connection:
        connection.execute(
            "WITH t AS (SELECT clock_timestamp()-INTERVAL '31 minutes' AS at) "
            "UPDATE approval SET approved_at=t.at,expires_at=t.at+INTERVAL '30 minutes' FROM t WHERE approval_id=%s",
            (saved.approval_id,),
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED" and count(db, "maintenance_plan") == 2


def test_update_operation_stays_outside_create_scope(approved):
    db, service, _ = approved
    saved = prepare(service, [update()])
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
