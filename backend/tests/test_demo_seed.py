from uuid import uuid4

import pytest

from linescope import cli
from linescope.demo_seed import DEMO_EQUIPMENT, SeedConflict, seed_demo


def rows(db, table):
    # Only test-owned constant table names are accepted.
    assert table in {"equipment", "equipment_current_state"}
    with db.transaction() as connection:
        return connection.execute(f"SELECT * FROM {table} ORDER BY equipment_id").fetchall()


def test_seed_creates_states_and_repeat_is_non_mutating(db):
    db.migrate()
    assert seed_demo(db) == {"inserted": ["M-204", "M-208"], "retained": []}
    before = {table: rows(db, table) for table in ("equipment", "equipment_current_state")}
    assert [row["state_code"] for row in before["equipment_current_state"]] == [
        "STOPPED",
        "RUNNING",
    ]
    assert seed_demo(db) == {"inserted": [], "retained": ["M-204", "M-208"]}
    assert {table: rows(db, table) for table in before} == before
    with db.transaction() as connection:
        for table in (
            "dependency_relation",
            "production_operation_equipment_assignment",
            "update_request",
        ):
            assert connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


def test_repeat_preserves_changed_metadata_and_state(db):
    db.migrate()
    seed_demo(db)
    with db.transaction() as connection:
        connection.execute("UPDATE equipment SET equipment_name='Edited',active=false,version=2")
        connection.execute(
            "UPDATE equipment_current_state SET state_code='UNDER_MAINTENANCE',version=3"
        )
    before = {table: rows(db, table) for table in ("equipment", "equipment_current_state")}
    seed_demo(db)
    assert {table: rows(db, table) for table in before} == before


@pytest.mark.parametrize("conflict", ["code", "id", "missing_state"])
def test_conflict_rolls_back_all_inserts(db, conflict):
    db.migrate()
    equipment_id, code, name, _ = DEMO_EQUIPMENT[1]
    with db.transaction() as connection:
        connection.execute(
            """INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active)
               VALUES(%s,%s,%s,'machine',true)""",
            (
                uuid4() if conflict == "code" else equipment_id,
                "OTHER" if conflict == "id" else code,
                name,
            ),
        )
    before = rows(db, "equipment")
    with pytest.raises(SeedConflict):
        seed_demo(db)
    assert rows(db, "equipment") == before
    assert rows(db, "equipment_current_state") == []


def test_cli_seed_is_explicit_and_reports_result(db, monkeypatch, capsys):
    db.migrate()
    monkeypatch.setattr(cli.Settings, "env", lambda: db.settings)
    monkeypatch.setattr(cli, "Database", lambda settings: db)
    monkeypatch.setattr("sys.argv", ["linescope", "seed-demo"])
    cli.main()
    assert '"inserted": ["M-204", "M-208"]' in capsys.readouterr().out


def test_cli_conflict_exits_unsuccessfully(db, monkeypatch, capsys):
    db.migrate()
    seed_demo(db)
    with db.transaction() as connection:
        connection.execute("DELETE FROM equipment_current_state")
    monkeypatch.setattr(cli.Settings, "env", lambda: db.settings)
    monkeypatch.setattr(cli, "Database", lambda settings: db)
    monkeypatch.setattr("sys.argv", ["linescope", "seed-demo"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert "no current state" in capsys.readouterr().err
