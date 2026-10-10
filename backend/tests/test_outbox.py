"""Outbox append boundary, not a complete Graph Execute workflow."""

from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from test_dependency_prepare import create, disable, prepare, update
from test_dependency_prepare import service as dependency_fixture

from linescope.graph_locks import acquire_graph_mutation_lock
from linescope.outbox import enqueue_graph_target
from linescope.projection_payload import build_projection_payload, projection_payload_hash
from linescope.projection_state import ProjectionState


@pytest.fixture
def world(db):
    db, service = dependency_fixture.__wrapped__(db)
    return db, service, prepare(service, [create(), update(), disable()])


def events(db):
    with db.transaction() as c:
        return c.execute("SELECT * FROM graph_outbox ORDER BY aggregate_id").fetchall()


def test_saved_targets_become_complete_pending_events(world):
    db, _, saved = world
    with db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        ids = [
            enqueue_graph_target(c, saved.update_request_id, t)
            for t in saved.snapshot.data["targets"]
        ]
        assert events(db) == []
    rows = events(db)
    assert {r["outbox_id"] for r in rows} == set(ids)
    for row, target in zip(rows, saved.snapshot.data["targets"], strict=True):
        expected = build_projection_payload(target["target_type"], target["after"])
        assert row["payload"] == expected
        assert projection_payload_hash(row["payload"]) == projection_payload_hash(expected)
        assert row["aggregate_version"] == target["after"]["version"]
        assert str(row["aggregate_id"]) == target["target_id"]
        assert row["event_type"] == target["operation_type"]
        assert row["status"] == "PENDING" and row["attempt_count"] == 0
        assert (
            row["processed_at"]
            is row["processing_started_at"]
            is row["next_attempt_at"]
            is row["last_error"]
            is None
        )
    assert any(not r["payload"]["state"]["active"] for r in rows)


def test_all_events_roll_back_with_business_update(world):
    db, _, saved = world
    with pytest.raises(RuntimeError), db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        c.execute("UPDATE dependency_relation SET version=version+1")
        for target in saved.snapshot.data["targets"]:
            enqueue_graph_target(c, saved.update_request_id, target)
        raise RuntimeError("abort")
    assert events(db) == []
    with db.transaction() as c:
        assert all(r["version"] == 5 for r in c.execute("SELECT version FROM dependency_relation"))


def test_duplicate_aggregate_version_is_not_silently_ignored(world):
    db, _, saved = world
    target = saved.snapshot.data["targets"][0]
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        enqueue_graph_target(c, saved.update_request_id, target)
        enqueue_graph_target(c, saved.update_request_id, target)
    assert events(db) == []


@pytest.mark.parametrize(
    "field", ["after", "before", "operation_type", "expected_version", "target_id"]
)
def test_modified_saved_target_is_rejected(world, field):
    db, _, saved = world
    target = deepcopy(
        next(t for t in saved.snapshot.data["targets"] if t["operation_type"] == "UPDATE")
    )
    if field == "after":
        target[field]["required"] = False
    elif field == "before":
        target[field]["required"] = False
    elif field == "operation_type":
        target[field] = "CREATE"
    elif field == "expected_version":
        target[field] += 1
    else:
        target[field] = str(uuid4())
    with pytest.raises(ValueError), db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        enqueue_graph_target(c, saved.update_request_id, target)
    assert events(db) == []


def test_target_cannot_be_attached_to_another_request(world):
    db, service, saved = world
    other = prepare(service)
    with pytest.raises(ValueError, match="belong"), db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        enqueue_graph_target(c, other.update_request_id, saved.snapshot.data["targets"][0])
    assert events(db) == []


@pytest.mark.parametrize(
    "target", [None, {}, {"target_type": "EquipmentState"}, {"target_type": []}]
)
def test_unsupported_target_never_creates_event(world, target):
    db, _, saved = world
    with pytest.raises(ValueError), db.transaction() as c:
        enqueue_graph_target(c, saved.update_request_id, target)
    assert events(db) == []


def test_autocommit_cannot_save_a_detached_event(world):
    db, _, saved = world
    with db.connect() as c:
        with pytest.raises(ValueError, match="active PostgreSQL transaction"):
            enqueue_graph_target(c, saved.update_request_id, saved.snapshot.data["targets"][0])
    assert events(db) == []


def test_assignment_events_skip_parent_schedule_target(db):
    from test_production_assignment_prepare import prepare as assignment_prepare
    from test_production_assignment_prepare import service as assignment_fixture

    db, service = assignment_fixture.__wrapped__(db)
    saved = assignment_prepare(service)
    targets = [
        t
        for t in saved.snapshot.data["targets"]
        if t["target_type"] == "ProductionOperationEquipmentAssignment"
    ]
    assert targets
    with db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        for target in targets:
            enqueue_graph_target(c, saved.update_request_id, target)
    assert len(events(db)) == len(targets)
    assert all(r["aggregate_type"] == "ProductionOperationEquipmentAssignment" for r in events(db))


def test_committed_enqueue_moves_initialized_sync_gate_to_lagging(world):
    db, _, saved = world
    with db.transaction() as c:
        c.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL", (uuid4(),)
        )
    assert ProjectionState(db).observe().status == "CURRENT"
    with db.transaction() as c:
        acquire_graph_mutation_lock(c, shared=False)
        enqueue_graph_target(c, saved.update_request_id, saved.snapshot.data["targets"][0])
        assert ProjectionState(db).observe().status == "CURRENT"
    assert ProjectionState(db).observe().status == "LAGGING"
