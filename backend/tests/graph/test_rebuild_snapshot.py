from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from application.test_dependency_prepare import service as dependency_fixture
from psycopg.pq import TransactionStatus

from linescope.graph.graph_locks import acquire_graph_mutation_lock
from linescope.graph.rebuild_snapshot import read_rebuild_snapshot


@pytest.fixture
def world(db):
    database, _ = dependency_fixture.__wrapped__(db)
    return database


def test_all_source_types_and_disabled_records_are_retained(world):
    with world.transaction() as connection:
        acquire_graph_mutation_lock(connection, shared=False)
        connection.execute(
            "UPDATE dependency_relation SET active=false WHERE dependency_relation_id=%s",
            (UUID(int=200),),
        )
        connection.execute("UPDATE production_operation_equipment_assignment SET active=false")
        snapshot = read_rebuild_snapshot(connection)
        assert connection.info.transaction_status == TransactionStatus.INTRANS
        assert {node["entity_type"] for node in snapshot.nodes} == {
            "Equipment",
            "Process",
            "ProductionOperation",
            "Product",
            "InfrastructureResource",
        }
        assert any(not node["active"] for node in snapshot.nodes)
        assert len(snapshot.aggregates) == 3
        relation = next(
            item for item in snapshot.aggregates if item["aggregate_id"] == str(UUID(int=200))
        )
        assert relation["aggregate_version"] == 5
        assert relation["state"]["active"] is False
        assert relation["state"]["required"] is True
        assert relation["state"]["effective_from"].endswith("Z")
        assignment = next(
            item
            for item in snapshot.aggregates
            if item["aggregate_type"] == "ProductionOperationEquipmentAssignment"
        )
        assert assignment["state"]["active"] is False
        assert assignment["state"]["effective_to"] is None
        assert all("planned_status" not in node for node in snapshot.nodes)


@pytest.mark.parametrize("mode", [None, True])
def test_missing_or_shared_lock_cannot_supply_rebuild_snapshot(world, mode):
    with world.transaction() as connection:
        if mode is not None:
            acquire_graph_mutation_lock(connection, shared=mode)
        with pytest.raises(ValueError, match="exclusive"):
            read_rebuild_snapshot(connection)


def test_hash_is_source_state_not_observation_time(world):
    with world.transaction() as connection:
        acquire_graph_mutation_lock(connection, shared=False)
        first = read_rebuild_snapshot(connection)
        second = read_rebuild_snapshot(connection)
        assert first.snapshot_hash == second.snapshot_hash
        assert (
            replace(first, observed_at=first.observed_at + timedelta(days=1)).snapshot_hash
            == first.snapshot_hash
        )
        connection.execute(
            "UPDATE dependency_relation SET version=version+1 WHERE dependency_relation_id=%s",
            (UUID(int=200),),
        )
        changed = read_rebuild_snapshot(connection)
        assert first.snapshot_hash != changed.snapshot_hash


def test_empty_database_is_an_observed_empty_snapshot(db):
    db.migrate()
    with db.transaction() as connection:
        acquire_graph_mutation_lock(connection, shared=False)
        snapshot = read_rebuild_snapshot(connection)
        assert snapshot.nodes == snapshot.aggregates == ()
        assert snapshot.observed_at.tzinfo is not None
        assert len(snapshot.snapshot_hash) == 64


def test_source_read_uses_one_statement_and_does_not_commit(world):
    class ObservedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.info = connection.info
            self.calls = 0

        def execute(self, *args, **kwargs):
            self.calls += 1
            return self.connection.execute(*args, **kwargs)

    with pytest.raises(RuntimeError), world.transaction() as connection:
        acquire_graph_mutation_lock(connection, shared=False)
        connection.execute("UPDATE product SET version=9")
        observed = ObservedConnection(connection)
        snapshot = read_rebuild_snapshot(observed)
        # Isolation check, lock ownership check, one combined source read.
        assert observed.calls == 3
        assert (
            next(node for node in snapshot.nodes if node["entity_type"] == "Product")[
                "entity_version"
            ]
            == 9
        )
        raise RuntimeError("Caller rollback")
    with world.transaction() as connection:
        assert connection.execute("SELECT version FROM product").fetchone()["version"] == 1


def test_session_timezone_does_not_change_snapshot_hash(world):
    with world.transaction() as connection:
        acquire_graph_mutation_lock(connection, shared=False)
        connection.execute("SET LOCAL TIME ZONE 'UTC'")
        utc = read_rebuild_snapshot(connection)
        connection.execute("SET LOCAL TIME ZONE 'Asia/Tokyo'")
        tokyo = read_rebuild_snapshot(connection)
        assert utc.snapshot_hash == tokyo.snapshot_hash
        assert utc.aggregates == tokyo.aggregates
