"""PostgreSQL-only storage gate; no Neo4j generation is published by these tests."""

from contextlib import contextmanager
from importlib.resources import files
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_dependency_prepare import prepare
from test_dependency_prepare import service as dependency_fixture

from linescope.projection_state import ProjectionState
from linescope.reads import ToolError


@pytest.fixture
def world(db):
    db, service = dependency_fixture.__wrapped__(db)
    return db, service, prepare(service)


def insert_event(c, saved, **changes):
    target = saved.snapshot.data["targets"][0]
    target_id = c.execute(
        "SELECT update_target_id FROM update_target WHERE update_request_id=%s",
        (saved.update_request_id,),
    ).fetchone()["update_target_id"]
    row = dict(
        outbox_id=uuid4(),
        update_request_id=saved.update_request_id,
        update_target_id=target_id,
        aggregate_type=target["target_type"],
        aggregate_id=UUID(target["target_id"]),
        aggregate_version=target["after"]["version"],
        event_type=target["operation_type"],
        payload=Jsonb(
            dict(
                schema_version=1,
                aggregate_type=target["target_type"],
                aggregate_id=target["target_id"],
                aggregate_version=target["after"]["version"],
                state=target["after"],
            )
        ),
        status="PENDING",
        attempt_count=0,
    )
    row.update(changes)
    c.execute(
        "INSERT INTO graph_outbox(outbox_id,update_request_id,update_target_id,aggregate_type,aggregate_id,aggregate_version,event_type,payload,status,attempt_count) VALUES("
        "%(outbox_id)s,%(update_request_id)s,%(update_target_id)s,%(aggregate_type)s,%(aggregate_id)s,%(aggregate_version)s,%(event_type)s,%(payload)s,%(status)s,%(attempt_count)s)",
        row,
    )
    return row


def initialize_gate(db):
    generation = uuid4()
    with db.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL WHERE control_id=1",
            (generation,),
        )
    return generation


def test_initial_control_is_not_current_even_with_empty_outbox(world):
    db, _, _ = world
    observation = ProjectionState(db).observe()
    assert observation.status == "ERROR" and observation.active_generation is None
    assert observation.observed_at.tzinfo is not None
    assert observation.counts == dict(PENDING=0, PROCESSING=0, RETRYABLE=0, APPLIED=0, DEAD=0)
    with db.transaction() as c:
        assert c.execute(
            "SELECT fatal_error,rebuild_flag,rebuild_id FROM graph_projection_control"
        ).fetchone() == dict(fatal_error="NOT_INITIALIZED", rebuild_flag=False, rebuild_id=None)


@pytest.mark.parametrize(
    "status,expected",
    [
        ("PENDING", "LAGGING"),
        ("PROCESSING", "LAGGING"),
        ("RETRYABLE", "LAGGING"),
        ("APPLIED", "CURRENT"),
        ("DEAD", "ERROR"),
    ],
)
def test_entire_committed_event_set_controls_sync(world, status, expected):
    db, _, saved = world
    generation = initialize_gate(db)
    with db.transaction() as c:
        insert_event(c, saved, status=status)
    observation = ProjectionState(db).observe()
    assert observation.status == expected and observation.active_generation == generation
    assert observation.counts[status] == 1 and sum(observation.counts.values()) == 1


def test_rebuild_has_priority_over_missing_generation_fatal_error_and_dead(world):
    db, _, saved = world
    with db.transaction() as c:
        insert_event(c, saved, status="DEAD")
        c.execute("UPDATE graph_projection_control SET rebuild_flag=true,rebuild_id=%s", (uuid4(),))
    assert ProjectionState(db).observe().status == "REBUILDING"
    with db.transaction() as c:
        c.execute("UPDATE graph_projection_control SET rebuild_flag=false")
    assert ProjectionState(db).observe().status == "ERROR"


@pytest.mark.parametrize("condition", ["missing_control", "missing_generation", "fatal_error"])
def test_control_failures_never_report_current(world, condition):
    db, _, _ = world
    initialize_gate(db)
    with db.transaction() as c:
        if condition == "missing_control":
            c.execute("DELETE FROM graph_projection_control")
        elif condition == "missing_generation":
            c.execute("UPDATE graph_projection_control SET active_generation=NULL")
        else:
            c.execute("UPDATE graph_projection_control SET fatal_error='PROJECTION_FAILED'")
    assert ProjectionState(db).observe().status == "ERROR"


def test_retry_due_time_and_applied_watermarks_do_not_hide_pending_events(world):
    db, _, saved = world
    initialize_gate(db)
    with db.transaction() as c:
        insert_event(c, saved, outbox_id=UUID(int=1), status="RETRYABLE")
        insert_event(c, saved, outbox_id=UUID(int=2), aggregate_version=2, status="APPLIED")
        c.execute(
            "UPDATE graph_outbox SET next_attempt_at=clock_timestamp()+interval '1 day' WHERE status='RETRYABLE'"
        )
        c.execute("UPDATE graph_outbox SET processed_at=clock_timestamp() WHERE status='APPLIED'")
    observation = ProjectionState(db).observe()
    assert observation.status == "LAGGING"
    assert observation.counts["RETRYABLE"] == observation.counts["APPLIED"] == 1


def test_uncommitted_control_and_event_changes_are_not_visible(world):
    db, _, saved = world
    initialize_gate(db)
    with db.transaction() as c:
        insert_event(c, saved)
        c.execute("UPDATE graph_projection_control SET fatal_error='PROJECTION_FAILED'")
        observed = ProjectionState(db).observe()
        assert observed.status == "CURRENT" and observed.counts["PENDING"] == 0
    observed = ProjectionState(db).observe()
    assert observed.status == "ERROR" and observed.counts["PENDING"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        dict(status="UNKNOWN"),
        dict(attempt_count=-1),
        dict(aggregate_version=0),
        dict(aggregate_type=" "),
        dict(event_type=""),
        dict(payload=Jsonb([])),
        dict(payload=None),
        dict(update_request_id=uuid4()),
        dict(update_target_id=uuid4()),
    ],
)
def test_outbox_rejects_invalid_storage_rows(world, changes):
    db, _, saved = world
    with pytest.raises(psycopg.IntegrityError), db.transaction() as c:
        insert_event(c, saved, **changes)


def test_outbox_target_must_belong_to_same_request(world):
    db, service, saved = world
    other = prepare(service)
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction() as c:
        insert_event(c, saved, update_request_id=other.update_request_id)


def test_outbox_aggregate_version_is_unique(world):
    db, _, saved = world
    with db.transaction() as c:
        insert_event(c, saved)
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        insert_event(c, saved)
    assert ProjectionState(db).observe().counts["PENDING"] == 1


def test_control_is_singleton(world):
    db, _, _ = world
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction() as c:
        c.execute("INSERT INTO graph_projection_control(control_id) VALUES(2)")
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        c.execute("INSERT INTO graph_projection_control(control_id) VALUES(1)")


def test_outbox_write_rolls_back_with_business_change(world):
    db, _, saved = world
    with pytest.raises(RuntimeError), db.transaction() as c:
        c.execute("UPDATE dependency_relation SET version=version+1")
        insert_event(c, saved)
        raise RuntimeError("abort transaction")
    assert ProjectionState(db).observe().counts["PENDING"] == 0
    with db.transaction() as c:
        assert all(
            row["version"] == 5 for row in c.execute("SELECT version FROM dependency_relation")
        )


def test_upgrade_preserves_existing_requests_and_has_no_fabricated_events(db):
    root = files("linescope").joinpath("migrations")
    db.migrate(
        [
            (p.name, p.read_text())
            for p in root.iterdir()
            if p.name.endswith(".sql") and p.name < "006"
        ]
    )
    from test_update_request_schema import insert_request, insert_target

    with db.transaction() as c:
        request = insert_request(c)
        insert_target(c, request["update_request_id"])
    assert db.migrate() == ["006_graph_projection_storage.sql"]
    assert db.migrate() == []
    assert ProjectionState(db).observe().status == "ERROR"
    with db.transaction() as c:
        assert (
            c.execute("SELECT status FROM update_request").fetchone()["status"]
            == "WAITING_APPROVAL"
        )
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "error,code",
    [
        (psycopg.errors.QueryCanceled, "RESOURCE_BUSY"),
        (psycopg.errors.LockNotAvailable, "RESOURCE_BUSY"),
        (psycopg.OperationalError, "DEPENDENCY_UNAVAILABLE"),
        (psycopg.ProgrammingError, "INTERNAL_ERROR"),
    ],
)
def test_storage_failure_is_sanitized_and_never_a_normal_sync_state(error, code):
    class Down:
        @contextmanager
        def transaction(self):
            raise error("private-secret")
            yield

    with pytest.raises(ToolError) as caught:
        ProjectionState(Down()).observe()
    assert caught.value.code == code and "private-secret" not in caught.value.message
