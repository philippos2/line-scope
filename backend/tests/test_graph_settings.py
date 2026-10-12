import pytest
from fastapi.testclient import TestClient

from linescope.bootstrap import build_api_services
from linescope.interfaces.api import create_app
from linescope.settings import Settings

CONFIG = {
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_user": "query",
    "neo4j_password": "private-password",
}


@pytest.mark.parametrize(
    "field,value",
    [
        ("graph_max_depth", 0),
        ("graph_max_nodes", True),
        ("graph_max_paths", -1),
        ("graph_timeout_ms", 0),
        ("neo4j_uri", "http://localhost:7687"),
        ("neo4j_uri", "bolt://user:secret@localhost:7687"),
        ("neo4j_uri", "bolt://localhost:7687/path"),
        ("neo4j_user", ""),
        ("neo4j_password", ""),
        ("neo4j_database", ""),
    ],
)
def test_invalid_graph_configuration_rejected(field, value):
    with pytest.raises(ValueError):
        Settings(**{**CONFIG, field: value})


def test_graph_env_parsing_and_secret_repr(monkeypatch):
    for key, value in {**CONFIG, "graph_max_nodes": 25}.items():
        monkeypatch.setenv("LINESCOPE_" + key.upper(), str(value))
    settings = Settings.env()
    assert settings.graph_max_nodes == 25 and settings.neo4j_uri == CONFIG["neo4j_uri"]
    assert "private-password" not in repr(settings) and "localhost:7687" not in repr(settings)


def test_credentials_without_uri_rejected():
    with pytest.raises(ValueError):
        Settings(neo4j_password="secret")


class Driver:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class NoDatabase:
    def for_reads(self):
        return self

    def transaction(self):
        raise AssertionError("Construction must not access PostgreSQL")


def test_owned_driver_is_configured_and_closed_on_shutdown(monkeypatch):
    driver = Driver()
    calls = []

    def factory(uri, **kwargs):
        calls.append((uri, kwargs))
        return driver

    monkeypatch.setattr("linescope.bootstrap.GraphDatabase.driver", factory)
    settings = Settings(**CONFIG, users={"token": {"user_id": "u", "role": "floor"}})
    with TestClient(create_app(settings, NoDatabase())) as client:
        assert driver.closed == 0
        assert client.get("/health", headers={"Authorization": "Bearer token"}).status_code == 200
    assert driver.closed == 1
    assert calls[0][1]["max_transaction_retry_time"] == 0
    assert calls[0][1]["connection_acquisition_timeout"] == 5


def test_owned_driver_closed_when_service_construction_fails(monkeypatch):
    driver = Driver()
    monkeypatch.setattr("linescope.bootstrap.GraphDatabase.driver", lambda *a, **kw: driver)

    def broken(*a, **kw):
        raise ValueError("construction failed")

    monkeypatch.setattr("linescope.bootstrap.GraphAnalysisReader", broken)
    with pytest.raises(ValueError):
        build_api_services(Settings(**CONFIG), NoDatabase())
    assert driver.closed == 1
