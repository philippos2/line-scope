"""Actual LOGIN role permissions against disposable PostgreSQL, not SET ROLE mocks."""

import secrets
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from application.test_maintenance_prepare import AGENT_HASH, create_plan, identity
from application.test_maintenance_prepare import service as maintenance_fixture
from interfaces.test_maintenance_plan_approval_api import act, client_for
from interfaces.test_maintenance_plan_create_api import execute
from psycopg import sql
from psycopg.conninfo import make_conninfo

from linescope.application.reads import ReadTools
from linescope.application.tools import ToolDispatcher
from linescope.persistence.database import Database
from linescope.persistence.db_roles import (
    PROJECTION_ROLE,
    READ_ROLE,
    WRITE_ROLE,
    RoleProvisionError,
    provision_roles,
)


@pytest.fixture
def roles(db):
    db, _ = maintenance_fixture.__wrapped__(db)
    passwords = {role: secrets.token_hex(32) for role in (READ_ROLE, WRITE_ROLE, PROJECTION_ROLE)}
    try:
        provision_roles(
            db,
            query_password=passwords[READ_ROLE],
            runtime_password=passwords[WRITE_ROLE],
            projection_password=passwords[PROJECTION_ROLE],
        )
        stores = {
            role: Database(
                replace(
                    db.settings,
                    dsn=make_conninfo(
                        db.settings.dsn,
                        user=role,
                        password=password,
                    ),
                )
            )
            for role, password in passwords.items()
        }
        yield db, stores, passwords
    finally:
        with db.transaction() as connection:
            for role in (READ_ROLE, WRITE_ROLE, PROJECTION_ROLE):
                if connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
                ).fetchone():
                    connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                    connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_actual_roles_are_unprivileged_and_query_reads_work(roles):
    admin, stores, _ = roles
    for role, store in stores.items():
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT current_user AS name, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert row["name"] == role
            assert all(row[key] is False for key in row if key != "name")
    routed = Database(replace(stores[WRITE_ROLE].settings, read_dsn=stores[READ_ROLE].settings.dsn))
    result = ReadTools(routed).run(identity(), "get_equipment", {"equipment_id": str(UUID(int=10))})
    assert result.data["equipment_code"] == "EQ10"
    with admin.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 2


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(gen_random_uuid(),'X','X','machine',true)",
        "UPDATE equipment SET equipment_name='changed'",
        "DELETE FROM equipment",
        "TRUNCATE equipment",
        "CREATE TABLE forbidden(id int)",
        "CREATE TEMP TABLE forbidden(id int)",
        "SELECT * FROM update_audit_event",
        "SELECT * FROM update_request",
        "SELECT * FROM schema_migration",
    ],
)
def test_query_role_rejects_mutation_ddl_and_private_tables(roles, statement):
    _, stores, _ = roles
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[READ_ROLE].transaction() as connection:
            connection.execute(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE forbidden(id int)",
        "CREATE TEMP TABLE forbidden(id int)",
        "ALTER TABLE equipment ADD COLUMN forbidden text",
        "DROP TABLE equipment CASCADE",
        "DELETE FROM update_audit_event",
        "UPDATE business_update_history SET occurred_at=clock_timestamp()",
        "UPDATE graph_projection_control SET fatal_error=NULL",
        "SET ROLE linescope_test",
        "SELECT * FROM schema_migration",
    ],
)
def test_runtime_role_rejects_ddl_history_tampering_and_escalation(roles, statement):
    _, stores, _ = roles
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[WRITE_ROLE].transaction() as connection:
            connection.execute(statement)


def test_runtime_prepare_approve_execute_and_replay_work_without_admin_authority(roles):
    admin, stores, passwords = roles
    runtime = Database(
        replace(stores[WRITE_ROLE].settings, read_dsn=stores[READ_ROLE].settings.dsn)
    )
    saved = ToolDispatcher(runtime).run(
        identity(),
        "prepare_maintenance_plan_create",
        create_plan("ROLE-PLAN")["input"],
        retry_key=uuid4(),
        agent_input_hash=AGENT_HASH,
    )
    with client_for(runtime) as client:
        assert act(client, saved, "approve").status_code == 200
        response = execute(client, saved)
        assert response.status_code == 200 and response.json()["data"]["status"] == "COMPLETED"
        assert (
            execute(client, saved).json()["data"]["execution_result"]
            == response.json()["data"]["execution_result"]
        )
    with admin.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM update_audit_event").fetchone()["n"] == 3
        )
    provision_roles(
        admin,
        query_password=passwords[READ_ROLE],
        runtime_password=passwords[WRITE_ROLE],
        projection_password=passwords[PROJECTION_ROLE],
    )
    with stores[READ_ROLE].transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM maintenance_plan WHERE plan_code=%s", ("ROLE-PLAN",)
            ).fetchone()["n"]
            == 1
        )

    # The new economic workflow must work with the provisioned runtime/query
    # identities as well as the administrative test connection.
    from interfaces.test_economic_inputs_api import approve as approve_economic
    from interfaces.test_economic_inputs_api import body as economic_body
    from interfaces.test_economic_inputs_api import client_for as economic_client
    from interfaces.test_economic_inputs_api import execute as execute_economic
    from interfaces.test_economic_inputs_api import prepare as prepare_economic

    values = economic_body("ROLE-ECONOMIC")
    values["input"]["equipment_id"] = str(UUID(int=10))
    with economic_client(runtime) as client:
        economic = prepare_economic(client, values)
        assert approve_economic(client, economic).status_code == 200
        assert execute_economic(client, economic).status_code == 200
    with stores[READ_ROLE].transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM economic_input").fetchone()["n"] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[READ_ROLE].transaction() as connection:
            connection.execute("UPDATE economic_input SET version=version+1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[PROJECTION_ROLE].transaction() as connection:
            connection.execute("SELECT * FROM economic_input")

    from interfaces.test_capacity_inputs_api import approve as approve_capacity
    from interfaces.test_capacity_inputs_api import body as capacity_body
    from interfaces.test_capacity_inputs_api import client_for as capacity_client
    from interfaces.test_capacity_inputs_api import execute as execute_capacity
    from interfaces.test_capacity_inputs_api import prepare as prepare_capacity

    values = capacity_body("ROLE-CAPACITY")
    values["input"]["equipment_id"] = str(UUID(int=10))
    with admin.transaction() as connection:
        connection.execute(
            "INSERT INTO product(product_id,product_code,product_name,active) VALUES (%s,'ROLE-P','Product',true)",
            (values["input"]["product_id"],),
        )
    with capacity_client(runtime) as client:
        capacity = prepare_capacity(client, values)
        assert approve_capacity(client, capacity).status_code == 200
        assert execute_capacity(client, capacity).status_code == 200
        assert (
            client.get(
                f"/capacity-inputs/{capacity['canonical_snapshot']['targets'][0]['target_id']}",
                headers={"Authorization": "Bearer production"},
            ).status_code
            == 200
        )
    with stores[READ_ROLE].transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM capacity_input").fetchone()["n"] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[READ_ROLE].transaction() as connection:
            connection.execute("UPDATE capacity_input SET version=version+1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[PROJECTION_ROLE].transaction() as connection:
            connection.execute("SELECT * FROM capacity_input")

    from interfaces.test_safety_inputs_api import approve as approve_safety
    from interfaces.test_safety_inputs_api import body as safety_body
    from interfaces.test_safety_inputs_api import client_for as safety_client
    from interfaces.test_safety_inputs_api import execute as execute_safety
    from interfaces.test_safety_inputs_api import prepare as prepare_safety

    values = safety_body("ROLE-SAFETY")
    values["input"]["equipment_id"] = str(UUID(int=10))
    with safety_client(runtime) as client:
        safety = prepare_safety(client, values)
        assert approve_safety(client, safety).status_code == 200
        assert execute_safety(client, safety).status_code == 200
        assert (
            client.get(
                f"/safety-inputs/{safety['canonical_snapshot']['targets'][0]['target_id']}",
                headers={"Authorization": "Bearer production"},
            ).status_code
            == 200
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[READ_ROLE].transaction() as connection:
            connection.execute("UPDATE safety_input SET version=version+1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[PROJECTION_ROLE].transaction() as connection:
            connection.execute("SELECT * FROM safety_input")


def test_future_objects_are_denied_until_explicit_grants(roles):
    admin, stores, _ = roles
    with admin.transaction() as connection:
        connection.execute("CREATE TABLE future_secret(id int)")
        connection.execute("CREATE SEQUENCE future_sequence")
        connection.execute(
            "CREATE FUNCTION future_function() RETURNS int LANGUAGE sql AS 'SELECT 1'"
        )
    for store in stores.values():
        for statement in (
            "SELECT * FROM future_secret",
            "SELECT nextval('future_sequence')",
            "SELECT future_function()",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with store.transaction() as connection:
                    connection.execute(statement)


@pytest.mark.parametrize("password", ["", "x", "' OR 1=1 --", None])
def test_password_validation_rejects_without_database_access(password):
    with pytest.raises(RoleProvisionError):
        provision_roles(
            None, query_password=password, runtime_password="a" * 64, projection_password="c" * 64
        )


def test_private_env_upgrade_preserves_credentials_and_is_idempotent(tmp_path):
    import importlib.util

    source = Path(__file__).resolve().parents[3] / "scripts" / "upgrade_demo_env.py"
    spec = importlib.util.spec_from_file_location("upgrade_demo_env", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / ".env"
    original = "LINESCOPE_POSTGRES_PASSWORD=existing\nLINESCOPE_USERS='{}'"
    destination.write_text(original)
    destination.chmod(0o600)
    assert module.upgrade(destination)
    after = destination.read_text()
    assert after.startswith(original + "\n")
    assert (
        after.count("LINESCOPE_QUERY_PASSWORD=") == after.count("LINESCOPE_RUNTIME_PASSWORD=") == 1
    )
    assert after.count("LINESCOPE_PROJECTION_PASSWORD=") == 1
    assert after.count("LINESCOPE_NEO4J_PASSWORD=") == 1
    assert not module.upgrade(destination)
    assert destination.read_text() == after
    destination.chmod(0o644)
    with pytest.raises(ValueError):
        module.upgrade(destination)


def test_reprovision_clears_unexpected_column_permissions(roles):
    admin, stores, passwords = roles
    with admin.transaction() as connection:
        connection.execute("GRANT UPDATE (equipment_name) ON equipment TO linescope_query")
    provision_roles(
        admin,
        query_password=passwords[READ_ROLE],
        runtime_password=passwords[WRITE_ROLE],
        projection_password=passwords[PROJECTION_ROLE],
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[READ_ROLE].transaction() as connection:
            connection.execute("UPDATE equipment SET equipment_name='changed'")
    for table in ("equipment", "process", "product", "infrastructure_resource"):
        with stores[WRITE_ROLE].transaction() as connection:
            connection.execute(
                sql.SQL("SELECT version FROM {} FOR SHARE").format(sql.Identifier(table))
            )


def test_privileged_existing_role_is_rejected_without_changes(roles):
    admin, _, passwords = roles
    with admin.transaction() as connection:
        connection.execute("ALTER ROLE linescope_query CREATEDB")
    try:
        with pytest.raises(RoleProvisionError, match="administrator review"):
            provision_roles(
                admin,
                query_password=passwords[READ_ROLE],
                runtime_password=passwords[WRITE_ROLE],
                projection_password=passwords[PROJECTION_ROLE],
            )
        with admin.transaction() as connection:
            assert connection.execute(
                "SELECT rolcreatedb FROM pg_roles WHERE rolname=%s", (READ_ROLE,)
            ).fetchone()["rolcreatedb"]
            assert connection.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 2
    finally:
        with admin.transaction() as connection:
            connection.execute("ALTER ROLE linescope_query NOCREATEDB")


def test_failed_provision_rolls_back_role_creation_and_acl_changes(db):
    with pytest.raises(RoleProvisionError, match="provisioning failed"):
        provision_roles(
            db, query_password="a" * 64, runtime_password="b" * 64, projection_password="c" * 64
        )
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM pg_roles WHERE rolname=ANY(%s::text[])",
                ([READ_ROLE, WRITE_ROLE, PROJECTION_ROLE],),
            ).fetchone()["n"]
            == 0
        )
        assert connection.execute("SELECT current_schema() AS schema").fetchone()["schema"]


def test_admin_command_rejects_missing_secrets_before_migration(db, monkeypatch, capsys):
    from linescope import cli

    monkeypatch.setattr(cli.Settings, "env", lambda: db.settings)
    monkeypatch.setenv("LINESCOPE_QUERY_PASSWORD", "")
    monkeypatch.setenv("LINESCOPE_RUNTIME_PASSWORD", "")
    monkeypatch.setattr("sys.argv", ["linescope", "migrate-and-provision"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    assert "administrative procedure" in capsys.readouterr().err
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT to_regclass('schema_migration') AS name").fetchone()["name"]
            is None
        )


@pytest.mark.parametrize("deny_outbox", [False, True])
def test_assignment_execute_with_runtime_role_preserves_atomic_outbox(roles, deny_outbox):
    from application.test_production_assignment_approval import action
    from application.test_production_assignment_execute import execute as execute_assignment
    from application.test_production_assignment_prepare import prepare
    from application.test_production_assignment_prepare import service as production_fixture
    from application.test_production_schedule_approval import business, current

    from linescope.application.production_prepare import ProductionPrepare
    from linescope.application.proposals import ProposalError

    admin, stores, _ = roles
    production_fixture.__wrapped__(admin)
    runtime = stores[WRITE_ROLE]
    saved = prepare(ProductionPrepare(runtime))
    action(runtime, saved)
    before = business(admin)
    if deny_outbox:
        with admin.transaction() as connection:
            connection.execute("REVOKE INSERT ON graph_outbox FROM linescope_runtime")
        with pytest.raises(ProposalError):
            execute_assignment(runtime, saved)
        assert business(admin) == before
        state = current(admin, saved)
        assert state["status"] == state["approval_status"] == "APPROVED"
        with admin.transaction() as connection:
            assert connection.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] == 0
            assert (
                connection.execute("SELECT count(*) AS n FROM business_update_history").fetchone()[
                    "n"
                ]
                == 0
            )
            connection.execute("GRANT INSERT ON graph_outbox TO linescope_runtime")
    result = execute_assignment(runtime, saved)
    assert result["targets"] == saved.snapshot.data["targets"]
    assert execute_assignment(runtime, saved) == result
    with admin.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM graph_outbox").fetchone()["n"] > 0
        assert (
            connection.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"]
            == 1
        )


def test_same_query_and_runtime_password_is_rejected():
    with pytest.raises(RoleProvisionError):
        provision_roles(
            None, query_password="a" * 64, runtime_password="a" * 64, projection_password="c" * 64
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE equipment_current_state SET version=version+1",
        "INSERT INTO graph_outbox DEFAULT VALUES",
        "DELETE FROM graph_outbox",
        "UPDATE graph_outbox SET aggregate_version=aggregate_version+1",
        "UPDATE graph_outbox SET payload='{}'::jsonb",
        "UPDATE graph_projection_control SET fatal_error=NULL",
        "SELECT * FROM approval",
        "SELECT * FROM update_audit_event",
        "CREATE TABLE forbidden(id int)",
        "CREATE TEMP TABLE forbidden(id int)",
        "SET ROLE linescope_runtime",
    ],
)
def test_projection_role_denies_business_and_event_tampering(roles, statement):
    _, stores, _ = roles
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[PROJECTION_ROLE].transaction() as connection:
            connection.execute(statement)


def test_projection_role_claims_and_retries_with_real_leadership(roles):
    from graph.test_projection_queue import queued

    from linescope.graph.graph_leadership import graph_leadership
    from linescope.graph.projection_queue import ProjectionQueue
    from linescope.graph.projection_state import ProjectionState

    admin, stores, _ = roles
    queued.__wrapped__(admin)
    store = stores[PROJECTION_ROLE]
    queue = ProjectionQueue(store)
    with graph_leadership(store) as leader:
        claimed = queue.claim(leader)
        assert claimed["status"] == "PROCESSING"
        assert queue.fail(leader, claimed) is True
        with admin.transaction() as connection:
            assert (
                connection.execute(
                    "SELECT status FROM graph_outbox WHERE outbox_id=%s",
                    (claimed["outbox_id"],),
                ).fetchone()["status"]
                == "RETRYABLE"
            )
        ProjectionState(store).observe()


def test_projection_role_acknowledges_and_recovers_without_control_write(roles):
    from graph.test_projection_application import GENERATION, RecordingAdapter
    from graph.test_projection_queue import queued

    from linescope.graph.graph_leadership import graph_leadership
    from linescope.graph.projection_application import ProjectionApplication
    from linescope.graph.projection_queue import ProjectionQueue

    admin, stores, _ = roles
    queued.__wrapped__(admin)
    with admin.transaction() as connection:
        connection.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
            (GENERATION,),
        )
    store = stores[PROJECTION_ROLE]
    queue = ProjectionQueue(store)
    with graph_leadership(store) as leader:
        event = queue.claim(leader)
        assert ProjectionApplication(store).apply(leader, event, RecordingAdapter())
        expired = queue.claim(leader)
        with admin.transaction() as connection:
            connection.execute(
                "UPDATE graph_outbox SET processing_started_at=statement_timestamp()-interval '31 seconds' WHERE outbox_id=%s",
                (expired["outbox_id"],),
            )
        assert queue.recover_expired(leader) == [expired["outbox_id"]]


@pytest.mark.parametrize("password", ["", "' OR 1=1 --", None, "a" * 64, "b" * 64])
def test_projection_password_is_validated_before_database_access(password):
    with pytest.raises(RoleProvisionError):
        provision_roles(
            None, query_password="a" * 64, runtime_password="b" * 64, projection_password=password
        )


def test_reprovision_removes_projection_payload_and_control_permissions(roles):
    admin, stores, passwords = roles
    with admin.transaction() as connection:
        connection.execute("GRANT UPDATE (payload) ON graph_outbox TO linescope_projection")
        connection.execute("GRANT UPDATE ON graph_projection_control TO linescope_projection")
    provision_roles(
        admin,
        query_password=passwords[READ_ROLE],
        runtime_password=passwords[WRITE_ROLE],
        projection_password=passwords[PROJECTION_ROLE],
    )
    for statement in (
        "UPDATE graph_outbox SET payload='{}'::jsonb",
        "UPDATE graph_projection_control SET fatal_error=NULL",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with stores[PROJECTION_ROLE].transaction() as connection:
                connection.execute(statement)


def test_query_role_can_observe_graph_sync_with_shared_gate(roles):
    from linescope.graph.analysis_budget import GraphAnalysisBudget
    from linescope.graph.analysis_gate import GraphAnalysisGate
    from linescope.graph.projection_state import ProjectionState

    admin, stores, _ = roles
    generation = uuid4()
    with admin.transaction() as connection:
        connection.execute(
            "UPDATE graph_projection_control SET active_generation=%s,fatal_error=NULL",
            (generation,),
        )
    assert ProjectionState(stores[READ_ROLE]).observe().status == "CURRENT"
    with GraphAnalysisGate(stores[READ_ROLE]).open(
        GraphAnalysisBudget(timeout_ms=5000)
    ) as observed:
        assert observed.active_generation == generation


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT payload FROM graph_outbox",
        "SELECT * FROM graph_outbox",
        "UPDATE graph_outbox SET status='APPLIED'",
        "UPDATE graph_projection_control SET fatal_error=NULL",
    ],
)
def test_query_graph_metadata_grants_do_not_expose_payload_or_mutation(roles, statement):
    _, stores, _ = roles
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with stores[READ_ROLE].transaction() as connection:
            connection.execute(statement)
