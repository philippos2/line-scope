import os
import subprocess
import sys
from uuid import UUID

import pytest

from graph.test_neo4j_generation import graph_driver as graph_driver
from graph.test_rebuild_controller import adapters as adapters
from linescope.graph.administration import GraphAdministration
from linescope.graph.graph_leadership import GraphLeaderBusy, graph_leadership
from linescope.graph.projection_state import ProjectionState
from linescope.graph.rebuild_control import RebuildControl, RebuildControlRejected


@pytest.fixture
def source(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'M-204','Demo','machine',true)",
            (UUID(int=204),),
        )
    return db


def service(source, adapters):
    return GraphAdministration(source, adapters[1].driver)


def test_explicit_schema_and_first_rebuild_publish_verified_current(source, adapters):
    admin = service(source, adapters)
    admin.install_schema()
    first = admin.rebuild()
    assert first.node_count == 1
    observation = ProjectionState(source).observe()
    assert (
        observation.status == "CURRENT" and str(observation.active_generation) == first.generation
    )
    with graph_leadership(source) as leader:
        proof = adapters[1].observe_validation(generation=first.generation, leadership=leader)
    assert proof.snapshot_hash == first.snapshot_hash
    second = admin.rebuild()
    assert second.generation != first.generation and second.snapshot_hash == first.snapshot_hash
    with graph_leadership(source) as leader:
        adapters[1].require_verified(
            generation=first.generation, snapshot_hash=first.snapshot_hash, leadership=leader
        )


@pytest.mark.parametrize("operation", ["install_schema", "rebuild"])
def test_busy_leader_rejects_administrative_operation(source, adapters, operation):
    admin = service(source, adapters)
    with graph_leadership(source):
        with pytest.raises(GraphLeaderBusy):
            getattr(admin, operation)()
    assert ProjectionState(source).observe().active_generation is None


def test_recovery_is_explicit_and_validates_abandoned_flag(source, adapters):
    admin = service(source, adapters)
    with graph_leadership(source) as leader:
        RebuildControl(source).begin(leader)
    with pytest.raises(RebuildControlRejected):
        admin.rebuild()
    assert ProjectionState(source).observe().status == "REBUILDING"
    result = admin.rebuild(recover=True)
    assert ProjectionState(source).observe().status == "CURRENT"
    assert result.node_count == 1


def test_cli_schema_and_rebuild_on_real_storage(source, adapters):
    environment = {
        **os.environ,
        "LINESCOPE_DSN": source.settings.dsn,
        "LINESCOPE_NEO4J_URI": os.environ["LINESCOPE_TEST_NEO4J_URI"],
        "LINESCOPE_NEO4J_USER": "neo4j",
        "LINESCOPE_NEO4J_PASSWORD": "disposable-graph-password",
    }
    for command in ("install-graph-schema", "rebuild-graph"):
        result = subprocess.run(
            [sys.executable, "-m", "linescope.cli", command],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "disposable-graph-password" not in result.stdout + result.stderr
    assert ProjectionState(source).observe().status == "CURRENT"


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan"), 0.0001])
def test_schema_timeout_never_disables_server_timeout(timeout):
    from linescope.graph.neo4j_projection import install_projection_schema

    with pytest.raises((ValueError, TimeoutError)):
        install_projection_schema(object(), timeout_seconds=timeout)
