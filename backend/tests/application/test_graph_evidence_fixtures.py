"""The shared Evidence world must reject writes and keep schema isolation."""

import psycopg
import pytest
from graph.test_common_dependency_reader import graph_driver as graph_driver
from sqlalchemy import column, table, update
from sqlalchemy.dialects.postgresql.psycopg import dialect

from application.graph_evidence_fixtures import db as db
from application.graph_evidence_fixtures import evidence_world as evidence_world


def test_evidence_database_rejects_mutation_and_remains_usable(db):
    state = table("equipment_current_state", column("state_code"))
    compiled = update(state).values(state_code="UNKNOWN").compile(dialect=dialect())
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with db.transaction() as connection:
            connection.execute(str(compiled), compiled.params)
    with db.transaction() as connection:
        assert connection.execute(
            "SELECT state_code FROM equipment_current_state ORDER BY state_code"
        ).fetchall() == [{"state_code": "RUNNING"}, {"state_code": "STOPPED"}]


def test_factory_schema_is_separate_from_shared_evidence_world(db, database_factory):
    with db.transaction() as connection:
        evidence_schema = connection.execute("SELECT current_schema() AS name").fetchone()["name"]
    with database_factory() as isolated:
        with isolated.transaction() as connection:
            assert connection.execute("SELECT current_schema() AS name").fetchone()["name"] != (
                evidence_schema
            )
            assert (
                connection.execute(
                    "SELECT to_regclass('equipment_current_state') AS name"
                ).fetchone()["name"]
                is None
            )
        isolated.migrate()
        with isolated.transaction() as connection:
            assert (
                connection.execute("SELECT count(*) AS n FROM equipment_current_state").fetchone()[
                    "n"
                ]
                == 0
            )
