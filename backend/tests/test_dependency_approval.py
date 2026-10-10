"""Internal dependency approval; no Graph mutation or Outbox append."""

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from test_dependency_prepare import END, create, disable, prepare, uid, update
from test_dependency_prepare import service as dependency_fixture
from test_production_prepare import identity

from linescope.approvals import DependencyApproval
from linescope.logging import EventLogger
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def world(db):
    db, service = dependency_fixture.__wrapped__(db)
    return db, service, prepare(service, [create(), update(), disable()])


def action(db, saved, name="approve", actor=None, snapshot_hash=None):
    handler = DependencyApproval(db, EventLogger(stream=io.StringIO()))
    args = [actor or identity("manager", "approver"), str(saved.approval_id)]
    if name == "approve":
        args.append(snapshot_hash or saved.snapshot.snapshot_hash)
    return getattr(handler, name)(*args)


def current(db, saved):
    return ProposalStore(db).get(identity("maintenance"), str(saved.update_request_id))


def business(db):
    with db.transaction() as c:
        return c.execute(
            "SELECT jsonb_agg(to_jsonb(r) ORDER BY dependency_relation_id) AS rows FROM dependency_relation r"
        ).fetchone()["rows"]


@pytest.mark.parametrize("name", ["approve", "reject"])
def test_one_decision_for_create_update_disable_without_business_changes(world, name):
    db, _, saved = world
    before = business(db)
    result = action(db, saved, name)
    assert (
        result["status"]
        == result["approval_status"]
        == ("APPROVED" if name == "approve" else "REJECTED")
    )
    if name == "approve":
        assert result["expires_at"] - result["approved_at"] == timedelta(minutes=30)
    assert current(db, saved)["canonical_snapshot"] == saved.snapshot.data
    with pytest.raises(ProposalError) as caught:
        action(db, saved, name)
    assert caught.value.code == "INVALID_UPDATE_STATE"
    assert business(db) == before
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0


@pytest.mark.parametrize("fault", ["version", "missing", "value_without_version"])
def test_one_conflict_invalidates_whole_request(world, fault):
    db, _, saved = world
    with db.transaction() as c:
        sql = {
            "version": "UPDATE dependency_relation SET version=6 WHERE dependency_relation_id=%s",
            "missing": "DELETE FROM dependency_relation WHERE dependency_relation_id=%s",
            "value_without_version": "UPDATE dependency_relation SET required=false WHERE dependency_relation_id=%s",
        }[fault]
        c.execute(sql, (UUID(int=201),))
    before = business(db)
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "VERSION_CONFLICT" and caught.value.transition_committed
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == "INVALIDATED"
    assert business(db) == before


@pytest.mark.parametrize(
    "actor",
    [
        identity("floor", "other"),
        identity("maintenance", "other"),
        identity("production", "other"),
        identity("manager", "production1"),
    ],
)
def test_only_other_manager_can_approve(world, actor):
    db, _, saved = world
    with pytest.raises(ProposalError) as caught:
        action(db, saved, actor=actor)
    assert caught.value.code == "AUTHORIZATION_DENIED"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


def test_manager_cannot_self_approve_or_reject(db):
    db, service = dependency_fixture.__wrapped__(db)
    saved = prepare(service, context=identity("manager", "manager1"))
    for name in ("approve", "reject"):
        with pytest.raises(ProposalError) as caught:
            action(db, saved, name, actor=identity("manager", "manager1"))
        assert caught.value.code == "AUTHORIZATION_DENIED"


@pytest.mark.parametrize("same_id", [True, False])
def test_create_id_or_final_business_key_conflict_invalidates(world, same_id):
    db, _, saved = world
    row = next(
        t["after"] for t in saved.snapshot.data["targets"] if t["operation_type"] == "CREATE"
    )
    fields = [
        "dependency_relation_id",
        "source_entity_type",
        "source_entity_id",
        "target_entity_type",
        "target_entity_id",
        "relation_type",
        "effective_from",
        "effective_to",
        "required",
        "active",
        "version",
    ]
    row = dict(
        row, dependency_relation_id=row["dependency_relation_id"] if same_id else str(uuid4())
    )
    with db.transaction() as c:
        c.execute(
            "INSERT INTO dependency_relation("
            + ",".join(fields)
            + ") VALUES("
            + ",".join(["%s"] * len(fields))
            + ")",
            tuple(row[f] for f in fields),
        )
    with pytest.raises(ProposalError) as caught:
        action(db, saved)
    assert caught.value.code == "CREATE_CONFLICT"
    assert current(db, saved)["status"] == "INVALIDATED"


def test_same_request_can_transfer_a_business_key(db):
    db, service = dependency_fixture.__wrapped__(db)
    saved = prepare(
        service,
        [
            update(200, target_entity_id=uid(11)),
            create(
                source_entity_type="Equipment",
                source_entity_id=uid(100),
                target_entity_type="Process",
                target_entity_id=uid(10),
                effective_to=END,
            ),
        ],
    )
    assert action(db, saved)["status"] == "APPROVED"


def test_wrong_hash_preserves_pending_request(world):
    db, _, saved = world
    with pytest.raises(ProposalError) as caught:
        action(db, saved, snapshot_hash="0" * 64)
    assert caught.value.code == "APPROVAL_MISMATCH"
    assert current(db, saved)["status"] == "WAITING_APPROVAL"


@pytest.mark.parametrize(
    "name,conflict", [("approve", False), ("approve", True), ("reject", False)]
)
def test_audit_failure_rolls_back_decision_and_allows_retry(world, name, conflict):
    db, _, saved = world
    with db.transaction() as c:
        if conflict:
            c.execute(
                "UPDATE dependency_relation SET version=6 WHERE dependency_relation_id=%s",
                (UUID(int=201),),
            )
        c.execute(
            "CREATE FUNCTION fail_dependency_approval() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action IN ('APPROVE','INVALIDATE','REJECT') THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW; END $$"
        )
        c.execute(
            "CREATE TRIGGER fail_dependency_approval BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_dependency_approval()"
        )
    with pytest.raises(ProposalError) as caught:
        action(db, saved, name)
    assert caught.value.code == "INTERNAL_ERROR" and "private-secret" not in str(caught.value)
    assert current(db, saved)["status"] == "WAITING_APPROVAL"
    assert current(db, saved)["approval_status"] == "PENDING"
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action IN ('APPROVE','INVALIDATE','REJECT')"
            ).fetchone()["n"]
            == 0
        )
        c.execute("DROP TRIGGER fail_dependency_approval ON update_audit_event")
    if conflict:
        with pytest.raises(ProposalError) as retried:
            action(db, saved)
        assert retried.value.code == "VERSION_CONFLICT" and retried.value.transition_committed
        assert current(db, saved)["status"] == "INVALIDATED"
    else:
        assert action(db, saved, name)["status"] == (
            "APPROVED" if name == "approve" else "REJECTED"
        )


def test_parallel_approval_has_one_winner(world):
    db, _, saved = world

    def run(_):
        try:
            return action(db, saved)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, range(2))) == ["APPROVED", "INVALID_UPDATE_STATE"]


def test_parallel_approval_and_rejection_commit_one_decision(world):
    from threading import Barrier

    db, _, saved = world
    barrier = Barrier(2)
    before = business(db)

    def run(name):
        barrier.wait(timeout=5)
        try:
            return action(db, saved, name)["status"]
        except ProposalError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, ("approve", "reject")))
    assert results.count("INVALID_UPDATE_STATE") == 1
    winner = next(result for result in results if result != "INVALID_UPDATE_STATE")
    assert winner in {"APPROVED", "REJECTED"}
    assert current(db, saved)["status"] == current(db, saved)["approval_status"] == winner
    assert business(db) == before
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action IN ('APPROVE','REJECT')"
            ).fetchone()["n"]
            == 1
        )
        assert c.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 0
