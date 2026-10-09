import io
import json
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from test_execute import approved as approved_equipment
from test_proposals import context

from linescope.execute import EquipmentExecute
from linescope.logging import EventLogger
from linescope.proposals import ProposalError, ProposalStore
from linescope.settings import Settings


@pytest.fixture
def approved(db):
    return approved_equipment.__wrapped__(db)


def boundary(db, stream):
    return EquipmentExecute(
        db,
        Settings(users={"token": {"user_id": "approver", "role": "maintenance"}}),
        EventLogger(stream=stream),
    )


def test_success_and_replay_logged_after_commit(approved):
    db, saved = approved

    class Committed(io.StringIO):
        def write(self, text):
            assert (
                ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
                == "COMPLETED"
            )
            return super().write(text)

    stream = Committed()
    service = boundary(db, stream)
    actor = context("requester")
    first = service.execute(actor, str(saved.update_request_id))
    assert service.execute(actor, str(saved.update_request_id)) == first
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [event["replayed"] for event in events] == [False, True]
    assert all(event["request_id"] == str(actor.request_id) for event in events)
    assert events[0]["before_status"] == "APPROVED"
    assert events[1]["before_status"] == "COMPLETED"


def test_denied_execution_has_failure_audit_and_keeps_approved(approved):
    db, saved = approved
    stream = io.StringIO()
    with pytest.raises(ProposalError) as caught:
        boundary(db, stream).execute(context("other", "manager"), str(saved.update_request_id))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    with db.transaction() as c:
        audit = c.execute("SELECT * FROM update_audit_event WHERE action='FAILURE'").fetchone()
        assert audit["details"] == {"attempted_action": "EXECUTE"}
        assert audit["before_status"] == audit["after_status"] == "APPROVED"
    assert json.loads(stream.getvalue())["outcome"] == "rejected"


def test_execute_audit_rollback_followed_by_separate_failure_audit(approved):
    db, saved = approved
    with db.transaction() as c:
        c.execute(
            """CREATE FUNCTION fail_success_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='EXECUTE' THEN RAISE EXCEPTION 'private-secret'; END IF; RETURN NEW; END $$"""
        )
        c.execute(
            "CREATE TRIGGER fail_success_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_success_audit()"
        )
    stream = io.StringIO()
    with pytest.raises(ProposalError):
        boundary(db, stream).execute(context("requester"), str(saved.update_request_id))
    with db.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM update_audit_event WHERE action='FAILURE'"
            ).fetchone()["n"]
            == 1
        )
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
    assert "private-secret" not in stream.getvalue()
    assert json.loads(stream.getvalue())["outcome"] == "failure"


def test_audit_failure_fallback_keeps_original_denial(approved):
    db, saved = approved
    with db.transaction() as c:
        c.execute(
            """CREATE FUNCTION fail_all_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-secret'; END $$"""
        )
        c.execute(
            "CREATE TRIGGER fail_all_audit BEFORE INSERT ON update_audit_event FOR EACH ROW EXECUTE FUNCTION fail_all_audit()"
        )
    stream = io.StringIO()
    with pytest.raises(ProposalError) as caught:
        boundary(db, stream).execute(context("other", "manager"), str(saved.update_request_id))
    assert caught.value.code == "AUTHORIZATION_DENIED"
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [e["event"] for e in events] == ["audit.persist_failed", "execute.completed"]
    assert "private-secret" not in stream.getvalue()


def test_connection_failure_reports_unknown_and_sanitized_audit_fallback():
    class Unavailable:
        @contextmanager
        def transaction(self):
            raise psycopg.OperationalError("private-secret DSN")
            yield

    stream = io.StringIO()
    with pytest.raises(ProposalError) as caught:
        boundary(Unavailable(), stream).execute(context("requester"), str(uuid4()))
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [e["event"] for e in events] == ["audit.persist_failed", "execution.outcome_unknown"]
    assert events[-1]["outcome"] == "unknown" and events[-1]["level"] == "ERROR"
    assert "private-secret" not in stream.getvalue()


def test_stdout_failure_does_not_change_committed_result(approved):
    db, saved = approved

    class Broken(io.StringIO):
        def write(self, text):
            raise OSError("private-secret")

    result = boundary(db, Broken()).execute(context("requester"), str(saved.update_request_id))
    assert result["history_id"]
    assert (
        ProposalStore(db).get(context("requester"), str(saved.update_request_id))["status"]
        == "COMPLETED"
    )


def test_failure_after_completed_does_not_overwrite_terminal_state(approved):
    db, saved = approved
    stream = io.StringIO()
    service = boundary(db, stream)
    result = service.execute(context("requester"), str(saved.update_request_id))
    with pytest.raises(ProposalError):
        service.execute(context("other", "manager"), str(saved.update_request_id))
    assert service.execute(context("requester"), str(saved.update_request_id)) == result
    with db.transaction() as c:
        audit = c.execute("SELECT * FROM update_audit_event WHERE action='FAILURE'").fetchone()
        assert audit["before_status"] == audit["after_status"] == "COMPLETED"
