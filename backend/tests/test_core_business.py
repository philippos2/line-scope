"""Database guards remain effective even when the application checked earlier."""

from datetime import datetime, timezone

import pytest
from psycopg import sql
from test_execute import approved as equipment_fixture
from test_maintenance_plan_execute import approved as plan_fixture
from test_production_schedule_execute import world as schedule_fixture

from linescope.core_business import (
    update_equipment_state,
    update_maintenance_plan,
    update_production_schedule,
)


@pytest.mark.parametrize(
    "factory,table,key,writer,uses_clock",
    [
        (
            equipment_fixture,
            "equipment_current_state",
            "equipment_id",
            update_equipment_state,
            True,
        ),
        (plan_fixture, "maintenance_plan", "maintenance_plan_id", update_maintenance_plan, False),
        (
            schedule_fixture,
            "production_operation",
            "production_operation_id",
            update_production_schedule,
            True,
        ),
    ],
)
def test_stale_version_at_write_cannot_silently_overwrite(
    factory, table, key, writer, uses_clock, db
):
    prepared = factory.__wrapped__(db)
    saved = prepared[-1]
    target = saved.snapshot.data["targets"][0]
    read = sql.SQL("SELECT * FROM {} WHERE {}=%s").format(
        sql.Identifier(table), sql.Identifier(key)
    )
    executed_at = datetime.now(timezone.utc)
    with db.transaction() as c:
        before = c.execute(read, (target["target_id"],)).fetchone()
        stale = {**target, "expected_version": target["expected_version"] + 1}
        args = (executed_at,) if uses_clock else ()
        assert writer(c, stale, *args).rowcount == 0
        assert c.execute(read, (target["target_id"],)).fetchone() == before
        assert writer(c, target, *args).rowcount == 1
        assert (
            c.execute(read, (target["target_id"],)).fetchone()["version"] == before["version"] + 1
        )
        assert writer(c, target, *args).rowcount == 0


@pytest.mark.parametrize(
    "factory,table,key,locker",
    [
        (equipment_fixture, "equipment_current_state", "equipment_id", "lock_equipment_state"),
        (plan_fixture, "maintenance_plan", "maintenance_plan_id", "lock_maintenance_plan"),
    ],
)
def test_approval_target_lock_blocks_writer_until_transaction_end(factory, table, key, locker, db):
    import psycopg

    from linescope import core_business

    prepared = factory.__wrapped__(db)
    target = prepared[-1].snapshot.data["targets"][0]
    mutation = sql.SQL("UPDATE {} SET version=version+1 WHERE {}=%s").format(
        sql.Identifier(table), sql.Identifier(key)
    )
    with db.transaction() as holder:
        row = getattr(core_business, locker)(holder, target["target_id"])
        assert row["version"] == target["expected_version"]
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with db.transaction() as writer:
                writer.execute("SET LOCAL lock_timeout='50ms'")
                writer.execute(mutation, (target["target_id"],))
    with db.transaction() as writer:
        writer.execute("SET LOCAL lock_timeout='50ms'")
        assert writer.execute(mutation, (target["target_id"],)).rowcount == 1
