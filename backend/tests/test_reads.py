from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from linescope.api import create_app
from linescope.execution import ExecutionContext
from linescope.reads import GET_TOOLS, ReadTools, ToolError, json_value
from linescope.settings import ROLES, Settings

START = datetime(2020, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


def context(role="floor"):
    return ExecutionContext("trusted-user", role, uuid4())


@pytest.fixture
def world(db):
    db.migrate()
    keys = {key: uuid4() for _, key in GET_TOOLS.values()}
    keys["equipment_id"] = uuid4()
    keys["assignment_ids"] = [uuid4(), uuid4(), uuid4()]
    with db.transaction() as c:
        c.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,"
            "equipment_type,active,version) VALUES(%s,'EQ1','Machine','machine',true,7)",
            (keys["equipment_id"],),
        )
        c.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code,version) "
            "VALUES(%s,'STOPPED',3)",
            (keys["equipment_id"],),
        )
        c.execute(
            "INSERT INTO process(process_id,process_code,process_name,active) "
            "VALUES(%s,'P1','Process',true)",
            (keys["process_id"],),
        )
        c.execute(
            "INSERT INTO production_operation(production_operation_id,operation_code,"
            "process_id,planned_status,planned_start,planned_end,active,version) "
            "VALUES(%s,'OP1',%s,'PLANNED',%s,%s,true,4)",
            (keys["production_operation_id"], keys["process_id"], START, END),
        )
        c.execute(
            "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,"
            "planned_start,planned_end,plan_status) VALUES(%s,'MP1',%s,%s,%s,'PLANNED')",
            (keys["maintenance_plan_id"], keys["equipment_id"], START, END),
        )
        c.execute(
            "INSERT INTO product(product_id,product_code,product_name,active) "
            "VALUES(%s,'PROD1','Product',true)",
            (keys["product_id"],),
        )
        c.execute(
            "INSERT INTO infrastructure_resource(infrastructure_resource_id,resource_code,"
            "resource_name,resource_type,active) VALUES(%s,'R1','Power','power',true)",
            (keys["infrastructure_resource_id"],),
        )
        c.execute(
            "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,"
            "source_entity_id,target_entity_type,target_entity_id,relation_type,"
            "effective_from,required,active) "
            "VALUES(%s,'Equipment',%s,'InfrastructureResource',%s,'DEPENDS_ON',%s,true,true)",
            (
                keys["dependency_relation_id"],
                keys["equipment_id"],
                keys["infrastructure_resource_id"],
                START,
            ),
        )
        for identifier, start, end, active in [
            (keys["assignment_ids"][0], START, END, True),
            (keys["assignment_ids"][1], END, None, True),
            (keys["assignment_ids"][2], END + timedelta(hours=1), None, False),
        ]:
            c.execute(
                "INSERT INTO production_operation_equipment_assignment(assignment_id,"
                "production_operation_id,equipment_id,effective_from,effective_to,active) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    identifier,
                    keys["production_operation_id"],
                    keys["equipment_id"],
                    start,
                    end,
                    active,
                ),
            )
    return db, keys


@pytest.mark.integration
@pytest.mark.parametrize("tool", GET_TOOLS)
@pytest.mark.parametrize("role", sorted(ROLES))
def test_get_exact_record_all_authorized_roles(world, tool, role):
    db, keys = world
    table, key = GET_TOOLS[tool]
    result = ReadTools(db).run(context(role), tool, {key: str(keys[key])})
    with db.transaction() as c:
        from psycopg import sql

        expected = c.execute(
            sql.SQL("SELECT * FROM {} WHERE {}=%s").format(
                sql.Identifier(table), sql.Identifier(key)
            ),
            (keys[key],),
        ).fetchone()
    assert result.data == json_value(expected)
    assert result.data[key] == str(keys[key])
    assert result.data["version"] == expected["version"]
    assert result.evidence["source"] == "POSTGRESQL"
    assert result.evidence["tool"] == tool
    assert datetime.fromisoformat(result.evidence["observed_at"]).tzinfo is not None
    if tool == "get_equipment_state":
        assert result.data["state_code"] == "STOPPED" and result.data["version"] == 3
        assert result.data["updated_at"].endswith("Z")


@pytest.mark.integration
@pytest.mark.parametrize("tool", [*GET_TOOLS, "get_operation_equipment_assignments"])
def test_missing_record_is_not_fabricated(world, tool):
    db, _ = world
    key = GET_TOOLS[tool][1] if tool in GET_TOOLS else "production_operation_id"
    with pytest.raises(ToolError) as caught:
        ReadTools(db).run(context(), tool, {key: str(uuid4())})
    assert caught.value.code == "TARGET_NOT_FOUND"


@pytest.mark.integration
def test_missing_current_state_does_not_invent_unknown(world):
    db, keys = world
    with db.transaction() as c:
        c.execute(
            "DELETE FROM equipment_current_state WHERE equipment_id=%s", (keys["equipment_id"],)
        )
    with pytest.raises(ToolError, match="does not exist"):
        ReadTools(db).run(
            context(), "get_equipment_state", {"equipment_id": str(keys["equipment_id"])}
        )


@pytest.mark.integration
@pytest.mark.parametrize("at,index", [(START, 0), (END - timedelta(microseconds=1), 0), (END, 1)])
def test_assignment_half_open_periods_and_current_registration(world, at, index):
    db, keys = world
    result = ReadTools(db).run(
        context(),
        "get_operation_equipment_assignments",
        {
            "production_operation_id": str(keys["production_operation_id"]),
            "explicit_as_of": at.isoformat(),
        },
    )
    assert result.data["parent_version"] == 4
    assert [item["assignment_id"] for item in result.data["items"]] == [
        str(keys["assignment_ids"][index])
    ]
    assert result.data["temporal_scope"] == "CURRENT_REGISTRATION_AT_AS_OF"
    assert datetime.fromisoformat(result.data["as_of"]) == at
    with db.transaction() as c:
        c.execute(
            "UPDATE production_operation_equipment_assignment SET active=false WHERE assignment_id=%s",
            (keys["assignment_ids"][index],),
        )
    # Historical filtering evaluates current registration, not a restored past state.
    again = ReadTools(db).run(
        context(),
        "get_operation_equipment_assignments",
        {
            "production_operation_id": str(keys["production_operation_id"]),
            "explicit_as_of": at,
        },
    )
    assert again.data["items"] == []


@pytest.mark.integration
def test_all_active_assignments_unfiltered_and_empty_operation(world):
    db, keys = world
    reads = ReadTools(db)
    args = {"production_operation_id": str(keys["production_operation_id"])}
    result = reads.run(context(), "get_operation_equipment_assignments", args)
    assert [item["assignment_id"] for item in result.data["items"]] == sorted(
        str(value) for value in keys["assignment_ids"][:2]
    )
    assert result.data["as_of"] is None
    with db.transaction() as c:
        c.execute("UPDATE production_operation_equipment_assignment SET active=false")
    result = reads.run(context(), "get_operation_equipment_assignments", args)
    assert result.data["items"] == [] and result.data["parent_version"] == 4


class NoDatabase:
    @contextmanager
    def transaction(self):
        raise AssertionError("Rejected arguments must not access the database")
        yield


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"equipment_id": "not-a-uuid"},
        {"equipment_id": None},
        {"equipment_id": str(uuid4()), "role": "manager"},
        {"equipment_id": str(uuid4()), "authenticated_user_id": "forged"},
        {"equipment_id": str(uuid4()), "request_id": str(uuid4())},
        {"equipment_id": "'; DELETE FROM equipment; --"},
        [],
    ],
)
def test_invalid_or_spoofed_arguments_fail_before_database(args):
    with pytest.raises(ToolError) as caught:
        ReadTools(NoDatabase()).run(context(), "get_equipment", args)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "at",
    [
        None,
        123,
        "2020-01-01T00:00:00",
        "invalid",
        (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    ],
)
def test_invalid_or_future_as_of_rejected(at):
    with pytest.raises(ToolError) as caught:
        ReadTools(NoDatabase()).run(
            context(),
            "get_operation_equipment_assignments",
            {
                "production_operation_id": str(uuid4()),
                "explicit_as_of": at,
            },
        )
    assert caught.value.code == "INVALID_ARGUMENT"


def test_unknown_tools_and_missing_context_fail_closed():
    reads = ReadTools(NoDatabase())
    for tool in ["execute", "approve", "search_update_history", "SELECT 1", [], None]:
        with pytest.raises(ToolError) as caught:
            reads.run(context(), tool, {})
        assert caught.value.code == "INVALID_ARGUMENT"
    for identity in [None, {"role": "manager", "authenticated_user_id": "forged"}]:
        with pytest.raises(ToolError) as caught:
            reads.run(identity, "get_equipment", {"equipment_id": str(uuid4())})
        assert caught.value.code == "AUTHENTICATION_REQUIRED"


def test_schema_has_no_trusted_context_arguments():
    schemas = ReadTools(NoDatabase()).schemas()
    assert len(schemas) == 13
    for schema in schemas.values():
        assert schema["additionalProperties"] is False
        assert not {"role", "authenticated_user_id", "request_id"} & schema["properties"].keys()


@pytest.mark.parametrize(
    "error,code",
    [
        (psycopg.OperationalError("secret DSN"), "DEPENDENCY_UNAVAILABLE"),
        (psycopg.errors.LockNotAvailable("private SQL"), "RESOURCE_BUSY"),
        (psycopg.errors.QueryCanceled("private SQL"), "RESOURCE_BUSY"),
        (psycopg.ProgrammingError("private SQL"), "INTERNAL_ERROR"),
    ],
)
def test_database_errors_are_sanitized(error, code):
    class Down:
        @contextmanager
        def transaction(self):
            raise error
            yield

    with pytest.raises(ToolError) as caught:
        ReadTools(Down()).run(context(), "get_equipment", {"equipment_id": str(uuid4())})
    assert caught.value.as_dict() == {"code": code, "message": str(caught.value), "details": {}}
    assert "secret" not in str(caught.value) and "private" not in str(caught.value)


@pytest.mark.integration
def test_read_tools_do_not_mutate_business_records(world):
    from psycopg import sql

    db, keys = world
    tables = [row["tablename"] for row in db_snapshot_tables(db)]

    def contents():
        with db.transaction() as c:
            return {
                table: c.execute(
                    sql.SQL(
                        "SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text"
                    ).format(sql.Identifier(table))
                ).fetchall()
                for table in tables
            }

    before = contents()
    reads = ReadTools(db)
    for tool, (_, key) in GET_TOOLS.items():
        reads.run(context(), tool, {key: str(keys[key])})
    reads.run(
        context(),
        "get_operation_equipment_assignments",
        {
            "production_operation_id": str(keys["production_operation_id"]),
        },
    )
    assert contents() == before


def db_snapshot_tables(db):
    with db.transaction() as c:
        return c.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
        ).fetchall()


def test_api_injects_context_from_authentication_and_ignores_body_identity():
    settings = Settings(users={"valid": {"user_id": "floor1", "role": "floor"}})
    app = create_app(settings, NoDatabase())

    @app.post("/_test-context")
    def probe(request: Request):
        identity = request.state.execution_context
        return {
            "user_id": identity.authenticated_user_id,
            "role": identity.role,
            "request_id": str(identity.request_id),
        }

    with TestClient(app) as client:
        result = client.post(
            "/_test-context",
            headers={"Authorization": "Bearer valid"},
            json={"user_id": "manager1", "role": "manager"},
        )
        assert result.status_code == 200
        assert result.json()["user_id"] == "floor1" and result.json()["role"] == "floor"
        UUID(result.json()["request_id"])
        assert client.post("/_test-context").status_code == 401


@pytest.mark.integration
@pytest.mark.parametrize("tool", [*GET_TOOLS, "get_operation_equipment_assignments"])
def test_read_transaction_blocks_accidental_writes(world, tool):
    db, keys = world
    checked = []

    class GuardedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params=None):
            result = self.connection.execute(query, params)
            if isinstance(query, str) and query.startswith("SET TRANSACTION"):
                with (
                    pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
                    self.connection.transaction(),
                ):
                    self.connection.execute(
                        "UPDATE equipment SET equipment_name='accidental mutation' WHERE equipment_id=%s",
                        (keys["equipment_id"],),
                    )
                checked.append(True)
            return result

    class GuardedDatabase:
        @contextmanager
        def transaction(self):
            with db.transaction() as connection:
                yield GuardedConnection(connection)

    key = GET_TOOLS[tool][1] if tool in GET_TOOLS else "production_operation_id"
    result = ReadTools(GuardedDatabase()).run(context(), tool, {key: str(keys[key])})
    assert checked == [True]
    if tool in GET_TOOLS:
        assert result.data[key] == str(keys[key])
    else:
        assert result.data["parent_version"] == 4
        assert len(result.data["items"]) == 2


@pytest.mark.integration
@pytest.mark.parametrize("tool", GET_TOOLS)
def test_core_read_preserves_all_native_values_and_caller_transaction(world, tool):
    from linescope.core_reads import get_record_row

    db, keys = world
    attack = "'; DROP TABLE equipment; -- 日本語 %_"
    with db.transaction() as c:
        c.execute(
            "UPDATE equipment SET equipment_name=%s,active=false WHERE equipment_id=%s",
            (attack, keys["equipment_id"]),
        )
        table, key = GET_TOOLS[tool]
        from psycopg import sql

        expected = c.execute(
            sql.SQL("SELECT * FROM {} WHERE {}=%s").format(
                sql.Identifier(table), sql.Identifier(key)
            ),
            (keys[key],),
        ).fetchone()
        c.execute(
            sql.SQL("UPDATE {} SET version=version+1 WHERE {}=%s").format(
                sql.Identifier(table), sql.Identifier(key)
            ),
            (keys[key],),
        )
        expected["version"] += 1
        row = get_record_row(c, tool, keys[key])
        observed_at = row.pop("_observed_at")
        assert row == expected
        assert observed_at.tzinfo is not None
        # The bridge sees an uncommitted caller change and leaves the same
        # connection/transaction usable; no separate Engine transaction exists.
        assert c.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 1
        if tool == "get_equipment":
            assert row["equipment_name"] == attack and row["active"] is False


@pytest.mark.integration
@pytest.mark.parametrize("tool", GET_TOOLS)
def test_core_read_bind_uuid_kept_out_of_sql(world, tool):
    from linescope.core_reads import get_record_row

    db, keys = world
    calls = []

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params):
            calls.append((query, params))
            return self.connection.execute(query, params)

    with db.transaction() as c:
        assert get_record_row(RecordingConnection(c), tool, keys[GET_TOOLS[tool][1]])
    assert len(calls) == 1
    query, params = calls[0]
    assert str(keys[GET_TOOLS[tool][1]]) not in query
    assert list(params.values()) == [keys[GET_TOOLS[tool][1]]]


@pytest.mark.integration
@pytest.mark.parametrize(
    "at",
    [
        None,
        START,
        END,
        START - timedelta(microseconds=1),
        START.astimezone(timezone(timedelta(hours=9))),
    ],
)
def test_core_assignment_native_values_single_statement_and_transaction(world, at):
    from linescope.core_reads import get_assignment_rows

    db, keys = world
    identifier = keys["production_operation_id"]
    calls = []

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params):
            calls.append((query, params))
            return self.connection.execute(query, params)

    with db.transaction() as c:
        c.execute(
            "UPDATE production_operation SET version=99 WHERE production_operation_id=%s",
            (identifier,),
        )
        c.execute("UPDATE production_operation_equipment_assignment SET version=12")
        expected = c.execute(
            """SELECT p.version AS _parent_version,a.*
            FROM production_operation p
            LEFT JOIN production_operation_equipment_assignment a
              ON a.production_operation_id=p.production_operation_id AND a.active
             AND (%s::timestamptz IS NULL OR (a.effective_from<=%s AND
                  (a.effective_to IS NULL OR %s<a.effective_to)))
            WHERE p.production_operation_id=%s ORDER BY a.assignment_id""",
            (at, at, at, identifier),
        ).fetchall()
        rows = get_assignment_rows(RecordingConnection(c), identifier, at)
        assert [
            {key: value for key, value in row.items() if key != "_observed_at"} for row in rows
        ] == expected
        assert all(row["_parent_version"] == 99 for row in rows)
        assert len({row["_observed_at"] for row in rows}) == 1
        assert rows[0]["_observed_at"].tzinfo is not None
        assert c.execute("SELECT 1 AS n").fetchone()["n"] == 1
    assert len(calls) == 1
    query, params = calls[0]
    assert str(identifier) not in query and identifier in params.values()
    if at is not None:
        assert at in params.values() and at.isoformat() not in query
