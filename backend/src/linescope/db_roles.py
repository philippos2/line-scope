"""Administrative PostgreSQL DDL; never exposed as an API or Agent Tool.

Role/schema DDL is a PostgreSQL-specific Raw SQL exception. Passwords enter
through bound transaction-local settings, never Python SQL interpolation.
"""

import re

import psycopg
from psycopg import sql

from .database import MIGRATION_LOCK

READ_ROLE = "linescope_query"
WRITE_ROLE = "linescope_runtime"
READ_TABLES = (
    "equipment",
    "equipment_current_state",
    "maintenance_plan",
    "maintenance_record",
    "process",
    "production_operation",
    "product",
    "infrastructure_resource",
    "production_operation_equipment_assignment",
    "dependency_relation",
)
INSERT_TABLES = (
    "maintenance_plan",
    "maintenance_record",
    "production_operation_equipment_assignment",
    "dependency_relation",
    "update_request",
    "update_target",
    "approval",
    "update_audit_event",
    "business_update_history",
    "equipment_state_history",
    "graph_outbox",
)
UPDATE_TABLES = (
    "equipment_current_state",
    "maintenance_plan",
    "production_operation",
    "production_operation_equipment_assignment",
    "dependency_relation",
    "update_request",
    "approval",
)
RUNTIME_READ_TABLES = READ_TABLES + (
    "update_request",
    "update_target",
    "approval",
    "update_audit_event",
    "business_update_history",
    "equipment_state_history",
    "graph_outbox",
    "graph_projection_control",
)
# FOR SHARE requires an UPDATE privilege on at least one column. These master
# Objects have no runtime update Tool; version-only grants permit existing locks.
LOCK_TABLES = ("equipment", "process", "product", "infrastructure_resource")

ROLE_DDL = """
DO $provision$
DECLARE
  r text;
  p text;
BEGIN
  FOREACH r IN ARRAY ARRAY['linescope_query', 'linescope_runtime'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
    p := current_setting(CASE WHEN r = 'linescope_query'
         THEN 'linescope.query_password' ELSE 'linescope.runtime_password' END);
    EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                   'NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD %L', r, p);
  END LOOP;
END
$provision$;
"""


class RoleProvisionError(Exception):
    pass


def validate_passwords(query_password, runtime_password):
    if (
        any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (query_password, runtime_password)
        )
        or query_password == runtime_password
    ):
        raise RoleProvisionError("Distinct generated database passwords are required")


def provision_roles(database, *, query_password, runtime_password):
    """Reapply explicit grants after migrations, preserving all business rows.

    Dedicated LineScope DB only. Fixed role names must have no memberships,
    privileged attributes or owned objects. Existing unexpected authority is
    rejected rather than silently reused. Runtime never gets schema ownership.
    """
    validate_passwords(query_password, runtime_password)
    try:
        with database.transaction() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
            owner = connection.execute(
                "SELECT current_schema() AS schema, current_database() AS database, "
                "current_user AS owner, (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) AS admin"
            ).fetchone()
            if not owner["admin"] or not owner["schema"]:
                raise RoleProvisionError("Administrative connection and schema are required")
            conflict = connection.execute(
                """SELECT EXISTS(
                  SELECT 1 FROM pg_roles r WHERE r.rolname=ANY(%s::text[]) AND (
                    r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
                    OR EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid OR m.roleid=r.oid)
                    OR EXISTS(SELECT 1 FROM pg_shdepend d WHERE d.refclassid='pg_authid'::regclass
                              AND d.refobjid=r.oid AND d.deptype='o')
                  )) AS conflict""",
                ([READ_ROLE, WRITE_ROLE],),
            ).fetchone()["conflict"]
            if conflict:
                raise RoleProvisionError(
                    "Existing database role authority requires administrator review"
                )
            connection.execute(
                "SELECT set_config('linescope.query_password',%s,true)", (query_password,)
            )
            connection.execute(
                "SELECT set_config('linescope.runtime_password',%s,true)", (runtime_password,)
            )
            connection.execute(ROLE_DDL)
            schema = sql.Identifier(owner["schema"])
            db = sql.Identifier(owner["database"])
            roles = sql.SQL(", ").join(map(sql.Identifier, (READ_ROLE, WRITE_ROLE)))
            connection.execute(
                sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC, {}").format(db, roles)
            )
            connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, roles))
            connection.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC, {}").format(schema, roles)
            )
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, roles))
            for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                connection.execute(
                    sql.SQL("REVOKE ALL ON ALL {} IN SCHEMA {} FROM PUBLIC, {}").format(
                        sql.SQL(kind), schema, roles
                    )
                )
                # Global defaults matter for functions: a per-schema REVOKE
                # cannot remove PostgreSQL's global PUBLIC EXECUTE default.
                connection.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES FOR ROLE {} REVOKE ALL ON {} FROM PUBLIC, {}"
                    ).format(sql.Identifier(owner["owner"]), sql.SQL(kind), roles)
                )
                connection.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} REVOKE ALL ON {} FROM PUBLIC, {}"
                    ).format(sql.Identifier(owner["owner"]), schema, sql.SQL(kind), roles)
                )
            # Table-level REVOKE does not remove column-level grants. Clear
            # existing column ACLs as well before applying the fixed policy.
            columns = connection.execute(
                "SELECT c.relname, a.attname FROM pg_attribute a "
                "JOIN pg_class c ON c.oid=a.attrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND a.attnum>0 AND NOT a.attisdropped "
                "AND a.attacl IS NOT NULL ORDER BY c.relname,a.attnum",
                (owner["schema"],),
            ).fetchall()
            for column in columns:
                connection.execute(
                    sql.SQL("REVOKE ALL ({}) ON TABLE {}.{} FROM PUBLIC, {}").format(
                        sql.Identifier(column["attname"]),
                        schema,
                        sql.Identifier(column["relname"]),
                        roles,
                    )
                )
            for role, privilege, tables in (
                (READ_ROLE, "SELECT", READ_TABLES),
                (WRITE_ROLE, "SELECT", RUNTIME_READ_TABLES),
                (WRITE_ROLE, "INSERT", INSERT_TABLES),
                (WRITE_ROLE, "UPDATE", UPDATE_TABLES),
                (WRITE_ROLE, "UPDATE (version)", LOCK_TABLES),
            ):
                for table in tables:
                    connection.execute(
                        sql.SQL("GRANT {} ON TABLE {}.{} TO {}").format(
                            sql.SQL(privilege), schema, sql.Identifier(table), sql.Identifier(role)
                        )
                    )
    except psycopg.Error as error:
        raise RoleProvisionError("Database role provisioning failed") from error
