"""Separate query connection selection without privileged failure fallback."""

from dataclasses import replace
from uuid import UUID

import pytest
from conftest import db as database_fixture
from psycopg.conninfo import make_conninfo
from test_search_reads import identity

from linescope.database import Database
from linescope.reads import ReadTools, ToolError
from linescope.settings import Settings
from linescope.tools import ToolDispatcher


@pytest.fixture
def read_db():
    yield from database_fixture.__wrapped__()


@pytest.mark.parametrize("value", ["", " ", 1, False])
def test_invalid_read_dsn_is_rejected(value):
    with pytest.raises(ValueError, match="LINESCOPE_READ_DSN"):
        Settings(read_dsn=value)


def test_read_dsn_environment_is_secret(monkeypatch):
    monkeypatch.setenv("LINESCOPE_READ_DSN", "postgresql://query:read-secret@localhost/db")
    settings = Settings.env()
    assert settings.read_dsn == "postgresql://query:read-secret@localhost/db"
    assert "read-secret" not in repr(settings)
    assert "read-secret" not in repr(Database(settings).for_reads().settings)


def test_read_tools_use_separate_connection_without_redirecting_mutations(db, read_db):
    for store, name in ((db, "Mutation source"), (read_db, "Query source")):
        store.migrate()
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) "
                "VALUES(%s,%s,%s,%s,%s)",
                (UUID(int=10), "EQ10", name, "machine", True),
            )
    routed = Database(replace(db.settings, read_dsn=read_db.settings.dsn))
    for reads in (ReadTools(routed), ToolDispatcher(routed).reads):
        result = reads.run(identity(), "get_equipment", {"equipment_id": str(UUID(int=10))})
        assert result.data["equipment_name"] == "Query source"
    with routed.transaction() as connection:
        assert (
            connection.execute("SELECT equipment_name FROM equipment").fetchone()["equipment_name"]
            == "Mutation source"
        )
    assert routed.for_reads().settings.lock_ms == routed.settings.lock_ms
    assert routed.for_reads().settings.statement_ms == routed.settings.statement_ms


def test_failed_query_connection_never_falls_back_to_working_mutation_connection(db):
    assert db.check()
    unavailable = make_conninfo(db.settings.dsn, dbname="missing_linescope_query_database")
    routed = Database(replace(db.settings, read_dsn=unavailable))
    with pytest.raises(ToolError) as caught:
        ReadTools(routed).run(identity(), "get_equipment", {"equipment_id": str(UUID(int=10))})
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    assert "missing_linescope_query_database" not in caught.value.message
    assert routed.check()
