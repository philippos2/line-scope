from uuid import uuid4

import psycopg
import pytest
from test_proposals import AGENT_HASH, PREPARE_HASH, context, snapshot

from linescope.proposals import ProposalError, ProposalStore


def saved(db, owner, key=None, supersedes=None):
    return ProposalStore(db).save(
        owner,
        snapshot(owner, supersedes=supersedes),
        key or str(uuid4()),
        prepare_input_hash=PREPARE_HASH,
        agent_input_hash=AGENT_HASH,
    )


def audit_rows(db):
    with db.transaction() as connection:
        return connection.execute(
            "SELECT * FROM update_audit_event ORDER BY occurred_at,audit_event_id"
        ).fetchall()


def fail_audit(db, action="PREPARE"):
    assert action in {"PREPARE", "INVALIDATE"}
    with db.transaction() as connection:
        connection.execute(f"""CREATE FUNCTION reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action='{action}' THEN RAISE EXCEPTION 'private-audit-secret'; END IF;
            RETURN NEW; END $$""")
        connection.execute(
            "CREATE TRIGGER reject_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_audit()"
        )


def test_prepare_success_and_replay_have_one_durable_audit(db):
    db.migrate()
    owner, key = context(), str(uuid4())
    proposal = saved(db, owner, key)
    before = audit_rows(db)
    (event,) = before
    assert event["request_id"] == owner.request_id
    assert event["actor_id"] == owner.authenticated_user_id
    assert event["update_request_id"] == proposal.update_request_id
    assert event["approval_id"] == proposal.approval_id
    assert event["action"] == "PREPARE" and event["result_code"] == "OK"
    assert event["before_status"] is None and event["after_status"] == "WAITING_APPROVAL"
    assert event["details"] == {"target_count": 1}
    assert event["occurred_at"].tzinfo is not None
    assert saved(db, context(), key).replayed
    assert audit_rows(db) == before


def test_audit_foreign_key_preserves_referenced_approval(db):
    db.migrate()
    owner = context()
    proposal = saved(db, owner)
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction() as connection:
        connection.execute("DELETE FROM approval WHERE approval_id=%s", (proposal.approval_id,))
    assert len(audit_rows(db)) == 1


def test_audit_failure_rolls_back_proposal_targets_and_pending_approval(db):
    db.migrate()
    fail_audit(db)
    owner, key = context(), str(uuid4())
    with pytest.raises(ProposalError) as caught:
        saved(db, owner, key)
    assert caught.value.code == "INTERNAL_ERROR" and "private-audit-secret" not in str(caught.value)
    with db.transaction() as connection:
        for table in ("update_request", "update_target", "approval", "update_audit_event"):
            assert connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
        connection.execute("DROP TRIGGER reject_audit ON update_audit_event")
    assert not saved(db, owner, key).replayed


def test_replacement_audits_both_new_request_and_old_invalidation(db):
    db.migrate()
    owner = context()
    old = saved(db, owner)
    new = saved(db, owner, supersedes=str(old.update_request_id))
    events = audit_rows(db)
    assert len(events) == 3
    invalidation = next(event for event in events if event["action"] == "INVALIDATE")
    assert invalidation["update_request_id"] == old.update_request_id
    assert invalidation["approval_id"] == old.approval_id
    assert invalidation["before_status"] == "WAITING_APPROVAL"
    assert invalidation["after_status"] == "INVALIDATED"
    assert invalidation["details"] == {"replacement_update_request_id": str(new.update_request_id)}


@pytest.mark.parametrize("action", ["PREPARE", "INVALIDATE"])
def test_replacement_audit_failure_preserves_old_request(db, action):
    db.migrate()
    owner = context()
    old = saved(db, owner)
    before = audit_rows(db)
    fail_audit(db, action)
    with pytest.raises(ProposalError):
        saved(db, owner, supersedes=str(old.update_request_id))
    assert audit_rows(db) == before
    current = ProposalStore(db).get(owner, str(old.update_request_id))
    assert current["status"] == "WAITING_APPROVAL" and current["approval_status"] == "PENDING"
