from uuid import UUID

import pytest

from linescope.demo_graph_seed import FIXTURES, seed_graph_demo
from linescope.demo_seed import DEMO_EQUIPMENT, SeedConflict
from linescope.graph.projection_state import ProjectionState


@pytest.fixture
def source(db):
    db.migrate()
    return db


def counts(db):
    from sqlalchemy import func, select
    from sqlalchemy.dialects.postgresql.psycopg import dialect

    from linescope.persistence.core_demo_seed import TABLES

    with db.transaction() as connection:
        result = {}
        for name, table in TABLES.items():
            query = select(func.count()).select_from(table).compile(dialect=dialect())
            result[name] = next(
                iter(connection.execute(str(query), query.params).fetchone().values())
            )
        return result


def test_seed_contains_mixed_entities_relations_and_is_idempotent(source):
    first = seed_graph_demo(source)
    assert len(first["inserted"]) == len(FIXTURES) == 17
    before = counts(source)
    assert before == {
        "equipment": 2,
        "equipment_current_state": 2,
        "process": 2,
        "product": 2,
        "infrastructure_resource": 1,
        "production_operation": 2,
        "production_operation_equipment_assignment": 1,
        "dependency_relation": 9,
    }
    with source.transaction() as connection:
        control = connection.execute("SELECT * FROM graph_projection_control").fetchone()
    again = seed_graph_demo(source)
    assert again["inserted"] == [] and len(again["retained"]) == 17
    assert counts(source) == before
    with source.transaction() as connection:
        assert connection.execute("SELECT * FROM graph_projection_control").fetchone() == control
        for table in ("update_request", "approval", "business_update_history", "graph_outbox"):
            assert connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


def test_repeat_preserves_edited_name_state_and_versions(source):
    seed_graph_demo(source)
    with source.transaction() as connection:
        connection.execute("UPDATE equipment SET equipment_name='Edited',version=5")
        connection.execute(
            "UPDATE equipment_current_state SET state_code='UNDER_MAINTENANCE',version=7"
        )
        connection.execute("UPDATE process SET process_name='Edited',version=3")
    seed_graph_demo(source)
    with source.transaction() as connection:
        assert connection.execute(
            "SELECT DISTINCT version,state_code FROM equipment_current_state"
        ).fetchall() == [{"version": 7, "state_code": "UNDER_MAINTENANCE"}]
        assert connection.execute(
            "SELECT DISTINCT equipment_name,version FROM equipment"
        ).fetchall() == [{"equipment_name": "Edited", "version": 5}]


def test_identity_conflict_rolls_back_equipment_entities_and_control(source):
    with source.transaction() as connection:
        connection.execute(
            "INSERT INTO product(product_id,product_code,product_name,active) VALUES(%s,'P-100','Existing',true)",
            (UUID(int=100),),
        )
        before = connection.execute("SELECT * FROM graph_projection_control").fetchone()
    with pytest.raises(SeedConflict):
        seed_graph_demo(source)
    assert counts(source)["equipment"] == counts(source)["process"] == 0
    with source.transaction() as connection:
        assert connection.execute("SELECT * FROM graph_projection_control").fetchone() == before


def test_edited_relationship_rejected_without_reset_or_partial_commit(source):
    seed_graph_demo(source)
    with source.transaction() as connection:
        connection.execute(
            "UPDATE dependency_relation SET active=false,version=2 WHERE relation_type='PRECEDES'"
        )
        connection.execute("DELETE FROM product WHERE product_code='P-200'")
    before = counts(source)
    with pytest.raises(SeedConflict):
        seed_graph_demo(source)
    assert counts(source) == before
    with source.transaction() as connection:
        assert connection.execute(
            "SELECT DISTINCT active,version FROM dependency_relation WHERE relation_type='PRECEDES'"
        ).fetchall() == [{"active": False, "version": 2}]


def test_active_rebuild_rejects_seed_without_writes(source):
    with source.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
    with pytest.raises(SeedConflict):
        seed_graph_demo(source)
    assert counts(source)["equipment"] == 0
    assert ProjectionState(source).observe().status == "REBUILDING"


def test_other_relation_set_is_rejected_without_changes(source):
    from linescope.persistence.core_demo_seed import insert_row

    seed_graph_demo(source)
    row = next(
        row
        for name, _, row, _ in FIXTURES
        if name == "dependency_relation" and row["relation_type"] == "CAN_SUBSTITUTE"
    )
    with source.transaction() as connection:
        insert_row(
            connection,
            "dependency_relation",
            {
                **row,
                "dependency_relation_id": UUID(int=999),
                "source_entity_id": DEMO_EQUIPMENT[0][0],
                "target_entity_id": DEMO_EQUIPMENT[1][0],
            },
        )
    before = counts(source)
    with pytest.raises(SeedConflict):
        seed_graph_demo(source)
    assert counts(source) == before


def test_graph_seed_cli_is_explicit(source, monkeypatch, capsys):
    from linescope import cli

    monkeypatch.setattr(cli.Settings, "env", lambda: source.settings)
    monkeypatch.setattr(cli, "Database", lambda settings: source)
    monkeypatch.setattr("sys.argv", ["linescope", "seed-demo-graph"])
    cli.main()
    assert '"equipment"' in capsys.readouterr().out
    assert counts(source)["dependency_relation"] == 9
