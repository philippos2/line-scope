from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from linescope.api import create_app
from linescope.settings import Settings


def settings():
    return Settings(users={"test-token": {"user_id": "floor1", "role": "floor"}})


class Probe:
    def check(self):
        raise AssertionError("Liveness must not depend on a database connection")


def test_liveness_without_database_and_common_envelope():
    with TestClient(create_app(settings(), Probe())) as client:
        response = client.get("/health", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    body = response.json()
    UUID(body["request_id"])
    assert body["status"] == "ok" and body["data"]["alive"]
    assert set(body) == {
        "request_id",
        "context_id",
        "status",
        "answer",
        "data",
        "evidence",
        "warnings",
        "errors",
    }


@pytest.mark.parametrize("header", [None, "Bearer unknown", "Basic test-token"])
def test_authentication_fail_closed(header):
    with TestClient(create_app(settings(), Probe())) as client:
        response = client.get("/health", headers={"Authorization": header} if header else {})
    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == "AUTHENTICATION_REQUIRED"


def test_database_unavailable_is_sanitized_503():
    class Down:
        def check(self):
            raise psycopg.OperationalError("postgresql://user:secret@private-host/database")

    with TestClient(create_app(settings(), Down())) as client:
        response = client.get("/health/ready", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "secret" not in response.text and "private-host" not in response.text


@pytest.mark.parametrize(
    "values",
    [
        {"statement_ms": 0},
        {"lock_ms": -1},
        {"connect_seconds": True},
        {"dsn": ""},
        {"users": []},
        {"users": {"x": {"user_id": "u", "role": "root"}}},
    ],
)
def test_invalid_configuration_is_rejected(values):
    with pytest.raises(ValueError):
        Settings(**values)


def test_environment_and_secrets_hidden_in_repr(monkeypatch):
    monkeypatch.setenv("LINESCOPE_DSN", "postgresql://user:secret@localhost/database")
    monkeypatch.setenv("LINESCOPE_STATEMENT_MS", "250")
    monkeypatch.setenv("LINESCOPE_USERS", '{"secret-token":{"user_id":"u","role":"manager"}}')
    value = Settings.env()
    assert value.statement_ms == 250 and value.users["secret-token"]["role"] == "manager"
    assert "secret" not in repr(value)


@pytest.mark.integration
def test_real_postgresql_readiness_and_no_business_tables(db):
    with TestClient(create_app(settings(), db)) as client:
        response = client.get("/health/ready", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200 and response.json()["data"]["postgresql"] == "available"
    db.migrate()
    with db.transaction() as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
        ).fetchall()
    assert tables == [{"tablename": "schema_migration"}]


@pytest.mark.integration
def test_concurrent_migration_once_and_checksum_guard(db):
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: db.migrate(), range(2)))
    assert sorted(results, key=len) == [[], ["001_bootstrap.sql"]]
    assert db.migrate() == []
    with pytest.raises(ValueError, match="Applied migration was modified"):
        db.migrate([("001_bootstrap.sql", "SELECT 2;")])


@pytest.mark.integration
def test_failed_migration_rolls_back_ddl_and_version(db):
    db.migrate()
    with pytest.raises(psycopg.Error):
        db.migrate([("002_test.sql", "CREATE TABLE temporary_probe(id INTEGER); SELECT 1/0;")])
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT to_regclass('temporary_probe') AS table_name").fetchone()[
                "table_name"
            ]
            is None
        )
        assert not connection.execute(
            "SELECT 1 FROM schema_migration WHERE version='002_test.sql'"
        ).fetchone()
    assert db.migrate([("002_test.sql", "CREATE TABLE temporary_probe(id INTEGER);")]) == [
        "002_test.sql"
    ]


@pytest.mark.integration
def test_transaction_rollback(db):
    with db.transaction() as connection:
        connection.execute("CREATE TABLE temporary_probe(id INTEGER)")
    with pytest.raises(RuntimeError), db.transaction() as connection:
        connection.execute("INSERT INTO temporary_probe VALUES(1)")
        raise RuntimeError("Abort transaction")
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS count FROM temporary_probe").fetchone()["count"]
            == 0
        )
