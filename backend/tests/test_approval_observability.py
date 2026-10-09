import io
import json
from uuid import uuid4

import pytest
from test_approvals import prepared as equipment_prepared
from test_proposals import context

from linescope.approvals import EquipmentApproval
from linescope.demo_seed import DEMO_EQUIPMENT
from linescope.logging import EventLogger
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def prepared(db):
    return equipment_prepared.__wrapped__(db)


def service(db, stream=None):
    stream = stream if stream is not None else io.StringIO()
    return EquipmentApproval(db, EventLogger(stream=stream)), stream


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_success_logged_only_after_commit(prepared, action):
    db, saved = prepared

    class CommittedStream(io.StringIO):
        def write(self, text):
            current = ProposalStore(db).get(context("requester"), str(saved.update_request_id))
            assert current["status"] == ("APPROVED" if action == "approve" else "REJECTED")
            return super().write(text)

    boundary, stream = service(db, CommittedStream())
    args = (saved.snapshot.snapshot_hash,) if action == "approve" else ()
    getattr(boundary, action)(context("approver", "maintenance"), str(saved.approval_id), *args)
    event = json.loads(stream.getvalue())
    assert event["event"] == "approval.completed" and event["outcome"] == "success"
    assert event["update_request_id"] == str(saved.update_request_id)
    assert event["actor_id"] == "approver"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_denied_attempt_has_separate_failure_audit(prepared, action):
    db, saved = prepared
    boundary, stream = service(db)
    actor = context("outsider", "floor")
    args = (saved.snapshot.snapshot_hash,) if action == "approve" else ()
    with pytest.raises(ProposalError) as caught:
        getattr(boundary, action)(actor, str(saved.approval_id), *args)
    assert caught.value.code == "AUTHORIZATION_DENIED"
    with db.transaction() as c:
        event = c.execute("SELECT * FROM update_audit_event WHERE action='FAILURE'").fetchone()
        assert event["request_id"] == actor.request_id
        assert event["result_code"] == "AUTHORIZATION_DENIED"
        assert event["before_status"] == event["after_status"] == "WAITING_APPROVAL"
        assert event["details"] == {"attempted_action": action.upper()}
    assert json.loads(stream.getvalue())["outcome"] == "rejected"


def test_success_audit_failure_rolls_back_then_saves_failure_attempt(prepared):
    db, saved = prepared
    with db.transaction() as c:
        c.execute("""CREATE FUNCTION reject_success_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action = 'APPROVE' THEN RAISE EXCEPTION 'private-secret'; END IF;
            RETURN NEW; END $$""")
        c.execute(
            "CREATE TRIGGER reject_success_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_success_audit()"
        )
    boundary, stream = service(db)
    with pytest.raises(ProposalError):
        boundary.approve(
            context("approver", "maintenance"), str(saved.approval_id), saved.snapshot.snapshot_hash
        )
    with db.transaction() as c:
        assert c.execute(
            "SELECT action FROM update_audit_event ORDER BY occurred_at"
        ).fetchall() == [{"action": "PREPARE"}, {"action": "FAILURE"}]
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "WAITING_APPROVAL"
    )
    assert "private-secret" not in stream.getvalue()
    assert json.loads(stream.getvalue())["outcome"] == "failure"


def test_failure_audit_unavailable_logs_fallback_and_preserves_original_error(prepared):
    db, saved = prepared
    with db.transaction() as c:
        c.execute("""CREATE FUNCTION reject_all_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private-secret'; END $$""")
        c.execute(
            "CREATE TRIGGER reject_all_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION reject_all_audit()"
        )
    boundary, stream = service(db)
    with pytest.raises(ProposalError) as caught:
        boundary.reject(context("outsider", "floor"), str(saved.approval_id))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [e["event"] for e in events] == ["audit.persist_failed", "approval.completed"]
    assert events[0]["level"] == "ERROR"
    assert "private-secret" not in stream.getvalue()


def test_missing_approval_does_not_create_fictitious_audit(prepared):
    db, _ = prepared
    boundary, stream = service(db)
    with pytest.raises(ProposalError) as caught:
        boundary.reject(context("approver", "maintenance"), str(uuid4()))
    assert caught.value.code == "TARGET_NOT_FOUND"
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='FAILURE'"
            ).fetchone()["n"]
            == 0
        )
    assert json.loads(stream.getvalue())["result_code"] == "TARGET_NOT_FOUND"


def test_committed_conflict_does_not_duplicate_failure_audit(prepared):
    db, saved = prepared
    with db.transaction() as c:
        c.execute(
            "UPDATE equipment_current_state SET version=2 WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        )
    boundary, stream = service(db)
    with pytest.raises(ProposalError):
        boundary.approve(
            context("approver", "maintenance"), str(saved.approval_id), saved.snapshot.snapshot_hash
        )
    with db.transaction() as c:
        assert c.execute(
            "SELECT action FROM update_audit_event ORDER BY occurred_at"
        ).fetchall() == [{"action": "PREPARE"}, {"action": "INVALIDATE"}]
    event = json.loads(stream.getvalue())
    assert event["result_code"] == "VERSION_CONFLICT"
    assert event["update_request_id"] == str(saved.update_request_id)


def test_stdout_failure_does_not_change_committed_approval(prepared):
    db, saved = prepared

    class Broken(io.StringIO):
        def write(self, text):
            raise OSError("private-secret")

    boundary, _ = service(db, Broken())
    result = boundary.approve(
        context("approver", "maintenance"), str(saved.approval_id), saved.snapshot.snapshot_hash
    )
    assert result["status"] == "APPROVED"
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "APPROVED"
    )


def test_failed_retry_audit_observes_terminal_state_without_overwriting_it(prepared):
    db, saved = prepared
    boundary, _ = service(db)
    boundary.reject(context("approver", "maintenance"), str(saved.approval_id))
    with pytest.raises(ProposalError):
        boundary.reject(context("approver", "maintenance"), str(saved.approval_id))
    with db.transaction() as c:
        event = c.execute("SELECT * FROM update_audit_event WHERE action='FAILURE'").fetchone()
        assert event["before_status"] == event["after_status"] == "REJECTED"
        assert event["result_code"] == "INVALID_UPDATE_STATE"
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "REJECTED"
    )
