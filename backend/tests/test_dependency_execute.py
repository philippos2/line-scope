"""Dependency Execute validates the final set and atomically records projection work."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb
from test_dependency_approval import action, business, current
from test_dependency_approval import world as pending_fixture
from test_dependency_prepare import END, START, create, disable, prepare, uid, update
from test_dependency_prepare import service as dependency_fixture
from test_production_prepare import identity

from linescope.dependency_execute import DependencyExecute
from linescope.graph_locks import acquire_graph_mutation_lock
from linescope.logging import EventLogger
from linescope.projection_payload import build_projection_payload
from linescope.projection_state import ProjectionState
from linescope.proposals import ProposalError
from linescope.relations import normalize_relation_set
from linescope.settings import Settings


@pytest.fixture
def world(db):
    db, service, saved = pending_fixture.__wrapped__(db)
    action(db, saved)
    return db, service, saved


def handler(db, role="manager"):
    return DependencyExecute(
        db,
        Settings(users={"token": {"user_id": "approver", "role": role}}),
        EventLogger(stream=io.StringIO()),
    )


def execute(db, saved, actor=None, role="manager"):
    return handler(db, role).execute(actor or identity("maintenance"), str(saved.update_request_id))


def assert_no_execution(db):
    with db.transaction() as c:
        for table in ("business_update_history", "graph_outbox"):
            assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


def test_composite_commit_history_outbox_and_durable_replay(world):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
            (UUID(int=1000),),
        )
    assert ProjectionState(db).observe().status == "CURRENT"
    result = execute(db, saved)
    assert ProjectionState(db).observe().status == "LAGGING"
    assert result["targets"] == saved.snapshot.data["targets"]
    assert current(db, saved)["status"] == "COMPLETED"
    assert current(db, saved)["approval_status"] == "CONSUMED"
    expected = {t["target_id"]: t for t in result["targets"]}
    with db.transaction() as c:
        rows = c.execute(
            "SELECT to_jsonb(r)-'created_at'-'updated_at' AS state FROM dependency_relation r"
        ).fetchall()
        assert normalize_relation_set([r["state"] for r in rows]) == sorted(
            [t["after"] for t in result["targets"]], key=lambda r: r["dependency_relation_id"]
        )
        events = c.execute("SELECT * FROM graph_outbox").fetchall()
        assert len(events) == 3
        for event in events:
            target = expected[str(event["aggregate_id"])]
            assert str(event["update_request_id"]) == str(saved.update_request_id)
            assert event["payload"] == build_projection_payload(
                "DependencyRelation", target["after"]
            )
            assert event["event_type"] == target["operation_type"]
            assert event["aggregate_version"] == target["after"]["version"]
            assert event["status"] == "PENDING" and event["attempt_count"] == 0
        history = c.execute("SELECT * FROM business_update_history").fetchone()
        assert history["category"] == "DEPENDENCY"
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
        c.execute("UPDATE dependency_relation SET version=version+1")
    # Confirmed after values survive later SoR changes and lost approval role.
    assert execute(db, saved, role="floor") == result
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 3
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1


@pytest.mark.parametrize("fault", ["version", "missing", "value"])
def test_target_change_invalidates_all_without_outbox(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            {
                "version": "UPDATE dependency_relation SET version=6 WHERE dependency_relation_id=%s",
                "missing": "DELETE FROM dependency_relation WHERE dependency_relation_id=%s",
                "value": "UPDATE dependency_relation SET required=false WHERE dependency_relation_id=%s",
            }[fault],
            (UUID(int=201),),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "VERSION_CONFLICT"
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert business(db) == before
    assert_no_execution(db)


@pytest.mark.parametrize("fault", ["inactive", "missing"])
def test_endpoint_change_invalidates_whole_request(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "UPDATE infrastructure_resource SET active=false"
            if fault == "inactive"
            else "DELETE FROM infrastructure_resource"
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before
    assert_no_execution(db)


@pytest.mark.parametrize("fault", ["id", "key", "overlap"])
def test_new_relation_conflicts_after_approval(world, fault):
    db, _, saved = world
    state = next(
        t["after"] for t in saved.snapshot.data["targets"] if t["operation_type"] == "CREATE"
    )
    state = {
        **state,
        "dependency_relation_id": state["dependency_relation_id"] if fault == "id" else uid(900),
    }
    if fault == "id":
        state["effective_from"] = END
    elif fault == "overlap":
        state["effective_from"] = END
    with db.transaction() as c:
        c.execute(
            "INSERT INTO dependency_relation SELECT (jsonb_populate_record(NULL::dependency_relation,%s)).*",
            (Jsonb({**state, "created_at": START, "updated_at": START}),),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == (
        "BUSINESS_RULE_VIOLATION" if fault == "overlap" else "CREATE_CONFLICT"
    )
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before
    assert_no_execution(db)


@pytest.mark.parametrize(
    "table",
    [
        "dependency_relation",
        "business_update_history",
        "graph_outbox",
        "approval",
        "update_request",
        "update_audit_event",
    ],
)
def test_each_write_failure_rolls_back_everything_and_retry_succeeds(world, table):
    db, _, saved = world
    before = business(db)
    with db.transaction() as c:
        c.execute(
            "CREATE FUNCTION fail_dependency_execute() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-secret'; END $$"
        )
        event = (
            "UPDATE" if table in {"dependency_relation", "approval", "update_request"} else "INSERT"
        )
        c.execute(
            f"CREATE TRIGGER fail_dependency_execute BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION fail_dependency_execute()"
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "APPROVED"
    assert business(db) == before
    assert_no_execution(db)
    with db.transaction() as c:
        c.execute(f"DROP TRIGGER fail_dependency_execute ON {table}")
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]


@pytest.mark.parametrize(
    "actor,role,code",
    [
        (identity("maintenance", "other"), "manager", "AUTHORIZATION_DENIED"),
        (identity("floor"), "manager", "APPROVAL_INVALIDATED"),
        (identity("maintenance"), "production", "APPROVAL_INVALIDATED"),
    ],
)
def test_current_owner_and_roles(world, actor, role, code):
    db, _, saved = world
    with pytest.raises(ProposalError) as caught:
        execute(db, saved, actor, role)
    assert caught.value.code == code
    assert current(db, saved)["status"] == (
        "APPROVED" if code == "AUTHORIZATION_DENIED" else "INVALIDATED"
    )
    assert_no_execution(db)


def test_deadline_retires_without_writes(world):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "UPDATE approval SET approved_at=statement_timestamp()-interval '31 minutes',expires_at=statement_timestamp()-interval '1 minute'"
        )
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED"
    assert current(db, saved)["status"] == "EXPIRED"
    assert_no_execution(db)


def test_same_request_parallel_execute_replays_once(world):
    db, _, saved = world
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: execute(db, saved), range(2)))
    assert results[0] == results[1]
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 3


def test_key_swap_and_old_key_transfer_use_deferred_final_constraints(db):
    db, service = dependency_fixture.__wrapped__(db)
    saved = prepare(
        service,
        [
            update(200, source_entity_id=uid(101), target_entity_id=uid(11), effective_to=None),
            update(201, source_entity_id=uid(100), target_entity_id=uid(10), effective_to=END),
        ],
    )
    action(db, saved)
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]
    transferred = prepare(
        service,
        [
            update(201, target_entity_id=uid(11)),
            create(
                source_entity_type="Equipment",
                source_entity_id=uid(100),
                target_entity_type="Process",
                target_entity_id=uid(10),
                effective_to=END,
            ),
        ],
    )
    action(db, transferred)
    assert execute(db, transferred)["targets"] == transferred.snapshot.data["targets"]


def test_concurrent_requests_cannot_together_create_cycle(db):
    db, service = dependency_fixture.__wrapped__(db)
    saved = [
        prepare(
            service,
            [
                create(
                    source_entity_id=uid(a), target_entity_type="Process", target_entity_id=uid(b)
                )
            ],
        )
        for a, b in ((10, 11), (11, 10))
    ]
    for proposal in saved:
        action(db, proposal)
    barrier = Barrier(2)

    def run(proposal):
        barrier.wait(timeout=5)
        try:
            execute(db, proposal)
            return "COMPLETED"
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, saved)) == ["BUSINESS_RULE_VIOLATION", "COMPLETED"]
    assert sorted(current(db, s)["status"] for s in saved) == ["COMPLETED", "INVALIDATED"]
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 1


def test_graph_lock_precedes_request_row_lock_for_execute_and_retire(world):
    db, _, saved = world
    service = handler(db)
    # Probe from another connection at the exact Request-lock entry: the Graph
    # shared lock must already be unavailable in both execution transactions.
    original = service._load
    calls = []

    def load(c, request_id):
        from psycopg.errors import LockNotAvailable

        with pytest.raises(LockNotAvailable), db.transaction() as probe:
            probe.execute("SET LOCAL lock_timeout='50ms'")
            acquire_graph_mutation_lock(probe, shared=True)
        calls.append(request_id)
        return original(c, request_id)

    service._load = load
    with db.transaction() as c:
        c.execute(
            "UPDATE dependency_relation SET version=6 WHERE dependency_relation_id=%s",
            (UUID(int=200),),
        )
    with pytest.raises(ProposalError) as caught:
        service.execute(identity("maintenance"), str(saved.update_request_id))
    assert caught.value.code == "VERSION_CONFLICT" and len(calls) == 2


@pytest.mark.parametrize("shared", [True, False])
def test_graph_lock_timeout_preserves_approval_and_allows_retry(world, shared):
    from dataclasses import replace

    from linescope.database import Database

    db, _, saved = world
    before = business(db)
    short = Database(replace(db.settings, lock_ms=50))
    with db.transaction() as holder:
        acquire_graph_mutation_lock(holder, shared=shared)
        with pytest.raises(ProposalError) as caught:
            execute(short, saved)
    assert caught.value.code == "RESOURCE_BUSY"
    assert current(db, saved)["status"] == "APPROVED" and business(db) == before
    assert_no_execution(db)
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]


def test_late_outbox_insert_failure_rolls_back_earlier_events(world, monkeypatch):
    import linescope.dependency_execute as module

    db, _, saved = world
    before = business(db)
    original = module.enqueue_graph_target
    count = 0

    def fail_second(c, request_id, target):
        nonlocal count
        count += 1
        if count == 2:
            c.execute("SELECT 1/0")
        return original(c, request_id, target)

    monkeypatch.setattr(module, "enqueue_graph_target", fail_second)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "INTERNAL_ERROR" and count == 2
    assert current(db, saved)["status"] == "APPROVED" and business(db) == before
    assert_no_execution(db)


def test_deadline_reached_after_outbox_rolls_back_all_and_expires(world, monkeypatch):
    import linescope.execute as module

    db, _, saved = world
    before = business(db)
    original = module.validate_new_execute
    validations = 0

    def validate(context, proposal, approval, *, now):
        nonlocal validations
        validations += 1
        return original(
            context, proposal, approval, now=approval.expires_at if validations >= 3 else now
        )

    monkeypatch.setattr(module, "validate_new_execute", validate)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "APPROVAL_EXPIRED" and validations == 4
    assert current(db, saved)["status"] == "EXPIRED" and business(db) == before
    assert_no_execution(db)


def test_new_reverse_controls_relation_causes_cycle_after_approval(db):
    db, service = dependency_fixture.__wrapped__(db)
    saved = prepare(
        service,
        [
            create(
                source_entity_type="Equipment",
                source_entity_id=uid(101),
                target_entity_type="Equipment",
                target_entity_id=uid(100),
                relation_type="CONTROLS",
                required=False,
            )
        ],
    )
    action(db, saved)
    # Both CONTROLS directions together create a structural cycle.
    with db.transaction() as c:
        c.execute(
            "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,source_entity_id,target_entity_type,target_entity_id,relation_type,effective_from,effective_to,required,active,version) VALUES(%s,'Equipment',%s,'Equipment',%s,'CONTROLS',%s,NULL,false,true,1)",
            (UUID(int=900), UUID(int=100), UUID(int=101), START),
        )
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        execute(db, saved)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert current(db, saved)["status"] == "INVALIDATED" and business(db) == before
    assert_no_execution(db)


def test_latest_assignments_are_used_in_final_validation(world, monkeypatch):
    import linescope.dependency_execute as module

    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,1)",
            (UUID(int=301), UUID(int=20), UUID(int=101), START),
        )
    original = module.validate_dependency_cycles
    observations = []

    def validate(relations, assignments):
        observations.append(assignments)
        return original(relations, assignments)

    monkeypatch.setattr(module, "validate_dependency_cycles", validate)
    execute(db, saved)
    assert len(observations) == 1
    assert {a["assignment_id"] for a in observations[0]} == {uid(300), uid(301)}


def test_cycle_can_be_removed_by_disable_in_same_request(db):
    db, service = dependency_fixture.__wrapped__(db)
    saved = prepare(
        service,
        [
            disable(200),
            create(
                source_entity_id=uid(10), target_entity_type="Equipment", target_entity_id=uid(100)
            ),
        ],
    )
    action(db, saved)
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]


def test_unrelated_relation_change_does_not_invalidate(world):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,source_entity_id,target_entity_type,target_entity_id,relation_type,effective_from,effective_to,required,active,version) VALUES(%s,'Process',%s,'Product',%s,'PRODUCES',%s,NULL,false,true,1)",
            (UUID(int=900), UUID(int=10), UUID(int=30), START),
        )
    assert execute(db, saved)["targets"] == saved.snapshot.data["targets"]


def test_internal_dependency_execute_is_not_admitted_by_public_router(world):
    from linescope.execute import HumanExecute

    db, _, saved = world
    service = HumanExecute(db, Settings(), EventLogger(stream=io.StringIO()))
    with pytest.raises(ProposalError) as caught:
        service.execute(identity("maintenance"), str(saved.update_request_id))
    assert caught.value.code == "INVALID_ARGUMENT"
    assert current(db, saved)["status"] == "APPROVED"
    assert_no_execution(db)
