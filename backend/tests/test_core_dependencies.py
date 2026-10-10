"""Dependency DB guards and endpoint locks, independent of SQL spelling."""

from datetime import datetime, timezone
from uuid import UUID

import psycopg
import pytest
from test_dependency_execute import world as dependency_fixture

from linescope.core_dependencies import lock_dependency_endpoint, update_dependency_relation


@pytest.mark.parametrize("operation", ["UPDATE", "DISABLE"])
def test_stale_dependency_write_cannot_overwrite_or_reuse_version(db, operation):
    db, _, saved = dependency_fixture.__wrapped__(db)
    target = next(t for t in saved.snapshot.data["targets"] if t["operation_type"] == operation)
    read = "SELECT * FROM dependency_relation WHERE dependency_relation_id=%s"
    at = datetime.now(timezone.utc)
    with db.transaction() as c:
        before = c.execute(read, (target["target_id"],)).fetchone()
        stale = {**target, "expected_version": target["expected_version"] + 1}
        assert update_dependency_relation(c, stale, at).rowcount == 0
        assert c.execute(read, (target["target_id"],)).fetchone() == before
        assert update_dependency_relation(c, target, at).rowcount == 1
        after = c.execute(read, (target["target_id"],)).fetchone()
        assert after["dependency_relation_id"] == before["dependency_relation_id"]
        assert after["created_at"] == before["created_at"]
        assert after["version"] == before["version"] + 1
        assert after["active"] == target["after"]["active"]
        assert after["updated_at"] == at
        assert update_dependency_relation(c, target, at).rowcount == 0
        assert c.execute(read, (target["target_id"],)).fetchone() == after


@pytest.mark.parametrize(
    "kind,identifier,mutation",
    [
        ("Equipment", 100, "UPDATE equipment SET active=false WHERE equipment_id=%s"),
        (
            "InfrastructureResource",
            40,
            "UPDATE infrastructure_resource SET active=false WHERE infrastructure_resource_id=%s",
        ),
        ("Process", 10, "UPDATE process SET active=false WHERE process_id=%s"),
        ("Product", 30, "UPDATE product SET active=false WHERE product_id=%s"),
        (
            "ProductionOperation",
            20,
            "UPDATE production_operation SET active=false WHERE production_operation_id=%s",
        ),
    ],
)
def test_all_endpoint_share_locks_hold_until_transaction_end(db, kind, identifier, mutation):
    db, _, _ = dependency_fixture.__wrapped__(db)
    identifier = UUID(int=identifier)
    with db.transaction() as holder:
        assert lock_dependency_endpoint(holder, kind, str(identifier)) == {"active": True}
        assert lock_dependency_endpoint(holder, kind, str(UUID(int=9999))) is None
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with db.transaction() as writer:
                writer.execute("SET LOCAL lock_timeout='50ms'")
                writer.execute(mutation, (identifier,))
    with db.transaction() as writer:
        writer.execute("SET LOCAL lock_timeout='50ms'")
        assert writer.execute(mutation, (identifier,)).rowcount == 1
        assert lock_dependency_endpoint(writer, kind, str(identifier)) == {"active": False}


def test_endpoint_kind_cannot_be_used_as_a_sql_identifier(db):
    db, _, _ = dependency_fixture.__wrapped__(db)
    with db.transaction() as c:
        with pytest.raises(KeyError):
            lock_dependency_endpoint(c, "equipment; DROP TABLE equipment; --", str(UUID(int=100)))
        assert lock_dependency_endpoint(c, "Equipment", str(UUID(int=100))) == {"active": True}
