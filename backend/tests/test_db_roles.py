"""Actual LOGIN role permissions against disposable PostgreSQL, not SET ROLE mocks."""

import secrets
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_maintenance_plan_approval_api import act, client_for
from test_maintenance_plan_create_api import execute
from test_maintenance_prepare import AGENT_HASH, create_plan, identity
from test_maintenance_prepare import service as maintenance_fixture

from linescope.database import Database
from linescope.db_roles import READ_ROLE, WRITE_ROLE, RoleProvisionError, provision_roles
from linescope.reads import ReadTools
from linescope.tools import ToolDispatcher


@pytest.fixture
def roles(db):
    db, _ = maintenance_fixture.__wrapped__(db)
    passwords = {READ_ROLE: secrets.token_hex(32), WRITE_ROLE: secrets.token_hex(32)}
    try:
        provision_roles(
            db, query_password=passwords[READ_ROLE], runtime_password=passwords[WRITE_ROLE]
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
            for role in (READ_ROLE, WRITE_ROLE):
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
        admin, query_password=passwords[READ_ROLE], runtime_password=passwords[WRITE_ROLE]
    )
    with stores[READ_ROLE].transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM maintenance_plan WHERE plan_code=%s", ("ROLE-PLAN",)
            ).fetchone()["n"]
            == 1
        )


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
        provision_roles(None, query_password=password, runtime_password="a" * 64)


def test_private_env_upgrade_preserves_credentials_and_is_idempotent(tmp_path):
    import importlib.util

    source = Path(__file__).resolve().parents[2] / "scripts" / "upgrade_demo_env.py"
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
        admin, query_password=passwords[READ_ROLE], runtime_password=passwords[WRITE_ROLE]
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
                admin, query_password=passwords[READ_ROLE], runtime_password=passwords[WRITE_ROLE]
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
        provision_roles(db, query_password="a" * 64, runtime_password="b" * 64)
    with db.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM pg_roles WHERE rolname=ANY(%s::text[])",
                ([READ_ROLE, WRITE_ROLE],),
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
    from test_production_assignment_approval import action
    from test_production_assignment_execute import execute as execute_assignment
    from test_production_assignment_prepare import prepare
    from test_production_assignment_prepare import service as production_fixture
    from test_production_schedule_approval import business, current

    from linescope.production_prepare import ProductionPrepare
    from linescope.proposals import ProposalError

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
        provision_roles(None, query_password="a" * 64, runtime_password="a" * 64)
