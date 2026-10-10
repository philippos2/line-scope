"""Real PostgreSQL atomicity for fixed assignment diffs and parent versions."""

import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb
from test_production_assignment_approval import action
from test_production_assignment_prepare import END, NEW_END, START, prepare, target
from test_production_assignment_prepare import service as production_fixture
from test_production_prepare import identity
from test_production_schedule_approval import business, current

from linescope.assignments import normalize_operation_assignments
from linescope.canonical import normalize_timestamp
from linescope.database import Database
from linescope.execute import HumanExecute
from linescope.graph_locks import acquire_graph_mutation_lock
from linescope.logging import EventLogger
from linescope.production_assignment_execute import ASSIGNMENT, ProductionAssignmentExecute
from linescope.projection_payload import build_projection_payload
from linescope.proposals import ProposalError
from linescope.settings import Settings


@pytest.fixture
def world(db):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare(
        service, [target(20, patch={"planned_status": "CANCELLED"}), target(21, equipment=(102,))]
    )
    action(db, saved)
    return db, service, saved


def handler(db, role="production"):
    return ProductionAssignmentExecute(
        db,
        Settings(users={"token": {"user_id": "approver", "role": role}}),
        EventLogger(stream=io.StringIO()),
    )


def execute(db, saved, actor=None, role="production"):
    return handler(db, role).execute(actor or identity(), str(saved.update_request_id))


def assert_no_execution(db, before):
    assert business(db) == before
    with db.transaction() as c:
        for table in ("business_update_history", "graph_outbox"):
            assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


def assert_committed(db, saved, result):
    assert result["targets"] == saved.snapshot.data["targets"]
    assert current(db, saved)["status"] == "COMPLETED"
    assert current(db, saved)["approval_status"] == "CONSUMED"
    rows = business(db)
    assignments = {
        a["assignment_id"]: normalize_operation_assignments(a["production_operation_id"], [a])[0]
        for a in rows["assignments"]
    }
    operations = {p["production_operation_id"]: p for p in rows["operations"]}
    for t in result["targets"]:
        if t["target_type"] == ASSIGNMENT:
            assert assignments[t["target_id"]] == t["after"]
        else:
            p = dict(operations[t["target_id"]])
            assert normalize_timestamp(p.pop("updated_at")) == result["executed_at"]
            p.pop("created_at")
            p["planned_start"] = normalize_timestamp(p["planned_start"])
            p["planned_end"] = normalize_timestamp(p["planned_end"])
            if "equipment_assignments" in t["after"]:
                p["equipment_assignments"] = sorted(
                    [
                        a
                        for a in assignments.values()
                        if a["active"] and a["production_operation_id"] == t["target_id"]
                    ],
                    key=lambda a: a["assignment_id"],
                )
            assert p == t["after"] and p["version"] == t["expected_version"] + 1
    children = {t["target_id"]: t for t in result["targets"] if t["target_type"] == ASSIGNMENT}
    with db.transaction() as c:
        events = c.execute("SELECT * FROM graph_outbox").fetchall()
        assert len(events) == len(children)
        for e in events:
            t = children[str(e["aggregate_id"])]
            assert e["aggregate_type"] == ASSIGNMENT
            assert e["aggregate_version"] == t["after"]["version"]
            assert e["event_type"] == t["operation_type"]
            assert e["payload"] == build_projection_payload(ASSIGNMENT, t["after"])
            assert e["status"] == "PENDING" and e["attempt_count"] == 0
            assert str(e["update_request_id"]) == str(saved.update_request_id)
        history = c.execute("SELECT * FROM business_update_history").fetchone()
        assert history["category"] == "PRODUCTION_OPERATION"
        for side in ("before", "after"):
            assert [t["snapshot"] for t in history[f"{side}_snapshot"]["targets"]] == [
                t[side] for t in result["targets"]
            ]
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='EXECUTE'"
            ).fetchone()["n"]
            == 1
        )


def test_two_parents_and_all_diffs_history_outbox_and_replay(world):
    db, _, saved = world
    result = execute(db, saved)
    assert_committed(db, saved, result)
    before = business(db)
    assert execute(db, saved, role="floor") == result and business(db) == before
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 6


@pytest.mark.parametrize("variant", ["middle", "unbounded", "empty", "reuse", "mixed"])
def test_prepared_interval_replacement_is_applied_exactly(db, variant):
    db, service = production_fixture.__wrapped__(db)
    if variant == "reuse":
        with db.transaction() as c:
            c.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,%s,false,9)",
                (UUID(int=40), UUID(int=20), UUID(int=101), START, END),
            )
    inputs = {
        "middle": [target(start=END, end=NEW_END)],
        "unbounded": [target(end=None)],
        "empty": [target(equipment=(), end=None)],
        "reuse": [target()],
        "mixed": [
            target(21),
            {"production_operation_id": str(UUID(int=20)), "patch": {"planned_end": NEW_END}},
        ],
    }[variant]
    saved = prepare(service, inputs)
    action(db, saved)
    assert_committed(db, saved, execute(db, saved))


@pytest.mark.parametrize(
    "fault",
    ["parent", "assignment_version", "assignment_value", "missing_assignment", "added_active"],
)
def test_any_current_target_or_collection_change_retires_all(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        queries = {
            "parent": "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
            "assignment_version": "UPDATE production_operation_equipment_assignment SET version=5 WHERE assignment_id=%s",
            "assignment_value": "UPDATE production_operation_equipment_assignment SET effective_to=%s WHERE assignment_id=%s",
            "missing_assignment": "DELETE FROM production_operation_equipment_assignment WHERE assignment_id=%s",
        }
        if fault == "added_active":
            c.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,1)",
                (UUID(int=900), UUID(int=21), UUID(int=101), START),
            )
        else:
            params = (
                (END, UUID(int=31))
                if fault == "assignment_value"
                else (UUID(int=21 if fault == "parent" else 31),)
            )
            c.execute(queries[fault], params)
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert_no_execution(db, before)


@pytest.mark.parametrize("fault", ["id", "key"])
def test_create_collision_after_approval_is_rechecked(world, fault):
    db, _, saved = world
    child = next(t for t in saved.snapshot.data["targets"] if t["operation_type"] == "CREATE")
    state = {**child["after"], "active": False, "created_at": START, "updated_at": START}
    if fault == "id":
        state["effective_from"], state["effective_to"], state["equipment_id"] = (
            END,
            None,
            str(UUID(int=100)),
        )
    else:
        state["assignment_id"] = str(UUID(int=900))
    with db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment SELECT (jsonb_populate_record(NULL::production_operation_equipment_assignment,%s)).*",
            (Jsonb(state),),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "CREATE_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert_no_execution(db, before)


def test_missing_new_equipment_retires_without_changing_assignments(world):
    db, _, saved = world
    with db.transaction() as c:
        c.execute("DELETE FROM equipment WHERE equipment_id=%s", (UUID(int=101),))
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert_no_execution(db, before)


def test_new_global_dependency_cycle_after_approval_is_rejected(world):
    db, _, saved = world
    with db.transaction() as c:
        for number, left, right in ((900, 100, 101), (901, 101, 100)):
            c.execute(
                "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,source_entity_id,target_entity_type,target_entity_id,relation_type,effective_from,effective_to,required,active,version) VALUES(%s,'Equipment',%s,'Equipment',%s,'DEPENDS_ON',%s,NULL,true,true,1)",
                (UUID(int=number), UUID(int=left), UUID(int=right), START),
            )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert_no_execution(db, before)


@pytest.mark.parametrize(
    "table",
    [
        "production_operation",
        "production_operation_equipment_assignment",
        "business_update_history",
        "graph_outbox",
        "approval",
        "update_request",
        "update_audit_event",
    ],
)
def test_write_failure_at_each_stage_rolls_back_all_then_retry_succeeds(world, table):
    db, _, saved = world
    before = business(db)
    with db.transaction() as c:
        c.execute(
            "CREATE FUNCTION fail_assignment_execute() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-secret'; END $$"
        )
        event = (
            "UPDATE"
            if table
            in {
                "production_operation",
                "production_operation_equipment_assignment",
                "approval",
                "update_request",
            }
            else "INSERT"
        )
        c.execute(
            f"CREATE TRIGGER fail_assignment_execute BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION fail_assignment_execute()"
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "APPROVED"
    assert_no_execution(db, before)
    with db.transaction() as c:
        c.execute(f"DROP TRIGGER fail_assignment_execute ON {table}")
    assert_committed(db, saved, execute(db, saved))


def test_late_outbox_failure_rolls_back_earlier_events(world, monkeypatch):
    import linescope.production_assignment_execute as module

    db, _, saved = world
    before = business(db)
    original = module.enqueue_graph_target
    count = 0

    def append(c, request_id, target):
        nonlocal count
        count += 1
        if count == 2:
            c.execute("SELECT 1/0")
        return original(c, request_id, target)

    monkeypatch.setattr(module, "enqueue_graph_target", append)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and count == 2
    assert current(db, saved)["status"] == "APPROVED"
    assert_no_execution(db, before)


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
    assert caught.value.code == code
    assert current(db, saved)["status"] == (
        "APPROVED" if code == "AUTHORIZATION_DENIED" else "INVALIDATED"
    )
    assert_no_execution(db, before)


def test_expired_approval_does_not_apply_diffs(world):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',expires_at=statement_timestamp()-interval '1 minute'"
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED"
    assert_no_execution(db, before)


def test_deadline_reached_after_outbox_rolls_back_all(world, monkeypatch):
    import linescope.execute as module

    db, _, saved = world
    before = business(db)
    original = module.validate_new_execute
    count = 0

    def validate(context, proposal, approval, *, now):
        nonlocal count
        count += 1
        return original(context, proposal, approval, now=approval.expires_at if count >= 3 else now)

    monkeypatch.setattr(module, "validate_new_execute", validate)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED" and count == 4
    assert current(db, saved)["status"] == "EXPIRED"
    assert_no_execution(db, before)


@pytest.mark.parametrize("shared", [True, False])
def test_graph_lock_timeout_is_retryable(world, shared):
    db, _, saved = world
    short = Database(replace(db.settings, lock_ms=50))
    before = business(db)
    with db.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=shared)
        with pytest.raises(ProposalError) as caught:
            execute(short, saved)
    assert caught.value.code == "RESOURCE_BUSY"
    assert current(db, saved)["status"] == "APPROVED"
    assert_no_execution(db, before)
    assert_committed(db, saved, execute(db, saved))


def test_assignment_noop_schedule_change_needs_no_graph_lock_or_outbox(db):
    db, service = production_fixture.__wrapped__(db)
    saved = prepare(
        service, [target(equipment=(100,), end=None, patch={"planned_status": "CANCELLED"})]
    )
    action(db, saved)
    before = business(db)["assignments"]
    with db.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=True)
        assert_committed(db, saved, execute(Database(replace(db.settings, lock_ms=50)), saved))
    assert business(db)["assignments"] == before


def test_graph_lock_precedes_request_lock_even_when_retiring(world):
    from psycopg.errors import LockNotAvailable

    db, _, saved = world
    service = handler(db)
    original = service._load
    calls = []

    def load(c, request_id):
        with pytest.raises(LockNotAvailable), db.transaction() as probe:
            probe.execute("SET LOCAL lock_timeout='50ms'")
            acquire_graph_mutation_lock(probe, shared=True)
        calls.append(request_id)
        return original(c, request_id)

    service._load = load
    with db.transaction() as c:
        c.execute(
            "UPDATE production_operation SET version=8 WHERE production_operation_id=%s",
            (UUID(int=21),),
        )
    with pytest.raises(ProposalError) as caught:
        service.execute(identity(), str(saved.update_request_id))
    assert caught.value.code == "VERSION_CONFLICT" and len(calls) == 2


def test_same_request_parallel_execute_replays_once(world):
    db, _, saved = world
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: execute(db, saved), range(2)))
    assert results[0] == results[1]
    assert_committed(db, saved, results[0])


def test_overlapping_approved_requests_commit_only_one_assignment_update(world):
    db, service, left = world
    right = prepare(service, [target(20, equipment=(102,), end=None)])
    action(db, right)

    def run(saved):
        try:
            execute(db, saved)
            return "COMPLETED"
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, [left, right])) == ["COMPLETED", "VERSION_CONFLICT"]
    winner = next(s for s in [left, right] if current(db, s)["status"] == "COMPLETED")
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1
        assert {
            str(r["update_request_id"])
            for r in c.execute("SELECT update_request_id FROM graph_outbox")
        } == {str(winner.update_request_id)}


def test_public_execute_router_applies_assignment_targets(world):
    db, _, saved = world
    result = HumanExecute(
        db,
        Settings(users={"token": {"user_id": "approver", "role": "production"}}),
        EventLogger(stream=io.StringIO()),
    ).execute(identity(), str(saved.update_request_id))
    assert_committed(db, saved, result)


@pytest.mark.parametrize("fault", ["overlap", "invalid_timestamp"])
def test_final_global_periods_and_invalid_source_are_distinguished(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation(production_operation_id,operation_code,process_id,planned_start,planned_end,planned_status,active,version) VALUES(%s,'OP22',%s,%s,%s,'PLANNED',true,1)",
            (UUID(int=22), UUID(int=10), START, END),
        )
        if fault == "overlap":
            for number, start in ((900, START), (901, END)):
                c.execute(
                    "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,1)",
                    (UUID(int=number), UUID(int=22), UUID(int=100), start),
                )
        else:
            # PostgreSQL permits this year, while canonical Snapshot v1 does
            # not. An invalid source is an internal error, not a new rule.
            c.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,'10000-01-01 00:00:00+00',NULL,false,1)",
                (UUID(int=900), UUID(int=22), UUID(int=100)),
            )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == (
        "BUSINESS_RULE_VIOLATION" if fault == "overlap" else "INTERNAL_ERROR"
    )
    assert current(db, saved)["status"] == ("INVALIDATED" if fault == "overlap" else "APPROVED")
    assert_no_execution(db, before)


def test_reused_inactive_assignment_changed_after_approval_invalidates_all(db):
    db, service = production_fixture.__wrapped__(db)
    with db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,%s,false,9)",
            (UUID(int=40), UUID(int=20), UUID(int=101), START, END),
        )
    saved = prepare(service)
    action(db, saved)
    with db.transaction() as c:
        c.execute(
            "UPDATE production_operation_equipment_assignment SET version=10 WHERE assignment_id=%s",
            (UUID(int=40),),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"
    assert_no_execution(db, before)
