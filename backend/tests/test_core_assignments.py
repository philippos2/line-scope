"""Real DB guards at assignment query boundaries, independent of SQL spelling."""

from datetime import datetime, timezone
from uuid import UUID

import psycopg
import pytest
from test_production_assignment_execute import ASSIGNMENT
from test_production_assignment_execute import world as assignment_fixture

from linescope.core_assignments import lock_assignment_equipment, update_assignment


def test_stale_assignment_write_cannot_overwrite_or_change_immutable_keys(db):
    db, _, saved = assignment_fixture.__wrapped__(db)
    target = next(
        t
        for t in saved.snapshot.data["targets"]
        if t["target_type"] == ASSIGNMENT and t["operation_type"] != "CREATE"
    )
    read = "SELECT * FROM production_operation_equipment_assignment WHERE assignment_id=%s"
    at = datetime.now(timezone.utc)
    with db.transaction() as c:
        before = c.execute(read, (target["target_id"],)).fetchone()
        stale = {**target, "expected_version": target["expected_version"] + 1}
        assert update_assignment(c, stale, at).rowcount == 0
        assert c.execute(read, (target["target_id"],)).fetchone() == before
        assert update_assignment(c, target, at).rowcount == 1
        after = c.execute(read, (target["target_id"],)).fetchone()
        assert after["version"] == before["version"] + 1
        for key in (
            "assignment_id",
            "production_operation_id",
            "equipment_id",
            "effective_from",
            "created_at",
        ):
            assert after[key] == before[key]
        assert after["active"] == target["after"]["active"]
        assert after["updated_at"] == at
        assert update_assignment(c, target, at).rowcount == 0
        assert c.execute(read, (target["target_id"],)).fetchone() == after


def test_assignment_equipment_share_lock_holds_until_transaction_end(db):
    db, _, _ = assignment_fixture.__wrapped__(db)
    identifier = UUID(int=102)
    with db.transaction() as holder:
        assert lock_assignment_equipment(holder, []) == []
        rows = lock_assignment_equipment(holder, [str(identifier)])
        assert rows == [{"equipment_id": identifier}]
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with db.transaction() as writer:
                writer.execute("SET LOCAL lock_timeout='50ms'")
                writer.execute(
                    "UPDATE equipment SET version=version+1 WHERE equipment_id=%s", (identifier,)
                )
    with db.transaction() as writer:
        writer.execute("SET LOCAL lock_timeout='50ms'")
        assert (
            writer.execute(
                "UPDATE equipment SET version=version+1 WHERE equipment_id=%s", (identifier,)
            ).rowcount
            == 1
        )
