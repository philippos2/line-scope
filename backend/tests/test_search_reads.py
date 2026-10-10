from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from psycopg import sql

from linescope.execution import ExecutionContext
from linescope.reads import SEARCH_TOOLS, ReadTools, ToolError


def identity(user="user1", role="floor"):
    return ExecutionContext(user, role, uuid4())


@pytest.fixture
def search_world(db):
    db.migrate()
    with db.transaction() as c:
        for index, name in enumerate(["Alpha Press", "beta", "ALPHA_Press", "Alpha%", "other"], 1):
            c.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,"
                "equipment_type,active) VALUES(%s,%s,%s,'machine',%s)",
                (UUID(int=index), f"EQ{index}", name, index != 5),
            )
        for index in [11, 12]:
            c.execute(
                "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,"
                "planned_start,planned_end,plan_status) VALUES(%s,%s,%s,'2020-01-01T00:00:00Z',"
                "'2020-01-02T00:00:00Z',%s)",
                (
                    UUID(int=index),
                    f"MP{index}",
                    UUID(int=index - 10),
                    "PLANNED" if index == 11 else "CANCELLED",
                ),
            )
        for index in [21, 22, 23]:
            c.execute(
                "INSERT INTO maintenance_record(maintenance_record_id,record_code,"
                "equipment_id,maintenance_plan_id,performed_at,result) "
                "VALUES(%s,%s,%s,%s,'2020-01-01T00:00:00Z','done')",
                (UUID(int=index), f"MR{index}", UUID(int=1), UUID(int=11) if index == 21 else None),
            )
        for index in [31, 32]:
            c.execute(
                "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,"
                "source_entity_id,target_entity_type,target_entity_id,relation_type,"
                "effective_from,required,active) "
                "VALUES(%s,'Equipment',%s,'Equipment',%s,'DEPENDS_ON','2020-01-01T00:00:00Z',true,%s)",
                (UUID(int=index), UUID(int=1), UUID(int=index - 29), index == 31),
            )
    return db


@pytest.mark.integration
@pytest.mark.parametrize("tool", SEARCH_TOOLS)
@pytest.mark.parametrize("role", ["floor", "maintenance", "production", "manager"])
def test_search_all_roles_and_id_order(search_world, tool, role):
    result = ReadTools(search_world).run(identity(role=role), tool, {})
    key = SEARCH_TOOLS[tool][1]
    assert result.data["items"]
    ids = [row[key] for row in result.data["items"]]
    assert ids == sorted(ids)
    assert result.data["next_cursor"] is None
    assert result.evidence["consistency"] == "LATEST_PER_CALL"
    assert datetime.fromisoformat(result.evidence["observed_at"]).tzinfo == timezone.utc


@pytest.mark.integration
@pytest.mark.parametrize(
    "tool,filters,expected",
    [
        ("search_equipment", {"equipment_code": "EQ2"}, [2]),
        ("search_equipment", {"name": "press"}, [1, 3]),
        ("search_equipment", {"name": "%"}, [4]),
        ("search_equipment", {"name": "_"}, [3]),
        ("search_equipment", {"name": "alpha", "equipment_code": "EQ3"}, [3]),
        ("search_equipment", {"equipment_code": "EQ5"}, [5]),
        ("search_maintenance_plans", {"equipment_id": str(UUID(int=1))}, [11]),
        ("search_maintenance_plans", {"plan_code": "MP12", "plan_status": "CANCELLED"}, [12]),
        (
            "search_maintenance_records",
            {"equipment_id": str(UUID(int=1)), "record_code": "MR21"},
            [21],
        ),
        ("search_maintenance_records", {"maintenance_plan_id": str(UUID(int=11))}, [21]),
        ("search_maintenance_records", {"maintenance_plan_id": None}, [22, 23]),
        ("search_dependency_relations", {"active": False}, [32]),
        (
            "search_dependency_relations",
            {
                "source": {"entity_type": "Equipment", "entity_id": str(UUID(int=1))},
                "target": {"entity_type": "Equipment", "entity_id": str(UUID(int=2))},
            },
            [31],
        ),
        ("search_dependency_relations", {"relation_type": "DEPENDS_ON", "active": True}, [31]),
        (
            "search_dependency_relations",
            {"source": {"entity_type": "Process", "entity_id": str(UUID(int=1))}},
            [],
        ),
        ("search_equipment", {"name": "'; DELETE FROM equipment; --"}, []),
    ],
)
def test_explicit_filters(search_world, tool, filters, expected):
    result = ReadTools(search_world).run(identity(), tool, {"filter": filters})
    key = SEARCH_TOOLS[tool][1]
    assert [row[key] for row in result.data["items"]] == [
        str(UUID(int=value)) for value in expected
    ]
    assert result.data["next_cursor"] is None


@pytest.mark.integration
@pytest.mark.parametrize(
    "tool,filters",
    [
        ("search_equipment", {"equipment_code": "missing"}),
        ("search_maintenance_plans", {"plan_code": "missing"}),
        ("search_maintenance_records", {"record_code": "missing"}),
        ("search_dependency_relations", {"relation_type": "CAN_SUBSTITUTE"}),
    ],
)
def test_empty_search_has_evidence(search_world, tool, filters):
    result = ReadTools(search_world).run(identity(), tool, {"filter": filters})
    assert result.data == {"items": [], "next_cursor": None}
    assert result.evidence["observed_at"]


@pytest.mark.integration
def test_keyset_pages_have_no_duplicates_and_allow_size_change(search_world):
    reads = ReadTools(search_world)
    first = reads.run(identity(), "search_equipment", {"page_size": 2})
    second = reads.run(
        identity(),
        "search_equipment",
        {
            "page_size": 1,
            "cursor": first.data["next_cursor"],
        },
    )
    third = reads.run(
        identity(),
        "search_equipment",
        {
            "page_size": 2,
            "cursor": second.data["next_cursor"],
        },
    )
    assert [
        row["equipment_id"] for page in [first, second, third] for row in page.data["items"]
    ] == [str(UUID(int=value)) for value in range(1, 6)]
    assert third.data["next_cursor"] is None


@pytest.mark.integration
def test_default_and_max_page_sizes_are_bounded(search_world):
    with search_world.transaction() as c:
        for value in range(100, 201):
            c.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,"
                "equipment_type,active) VALUES(%s,%s,'extra','machine',true)",
                (UUID(int=value), f"EQ{value}"),
            )
    reads = ReadTools(search_world)
    assert len(reads.run(identity(), "search_equipment", {}).data["items"]) == 20
    result = reads.run(identity(), "search_equipment", {"page_size": 100})
    assert len(result.data["items"]) == 100 and result.data["next_cursor"] is not None


@pytest.mark.integration
def test_pages_observe_later_commits_instead_of_restoring_snapshot(search_world):
    reads = ReadTools(search_world)
    first = reads.run(identity(), "search_equipment", {"page_size": 2})
    with search_world.transaction() as c:
        c.execute(
            "UPDATE equipment SET equipment_name='new current name',version=version+1 WHERE equipment_id=%s",
            (UUID(int=3),),
        )
        c.execute("DELETE FROM equipment WHERE equipment_id=%s", (UUID(int=5),))
    rest = reads.run(identity(), "search_equipment", {"cursor": first.data["next_cursor"]})
    assert rest.data["items"][0]["equipment_name"] == "new current name"
    assert rest.data["items"][0]["version"] == 2
    assert [row["equipment_id"] for row in rest.data["items"]] == [
        str(UUID(int=3)),
        str(UUID(int=4)),
    ]


@pytest.mark.integration
@pytest.mark.parametrize("change", ["user", "role", "tool", "filter", "tamper", "restart"])
def test_cursor_binding_and_tampering_fail_before_database(search_world, change):
    reads = ReadTools(search_world)
    first = reads.run(identity(), "search_equipment", {"page_size": 1})
    cursor = first.data["next_cursor"]
    who, tool, args = identity(), "search_equipment", {"cursor": cursor}
    if change == "user":
        who = identity(user="other")
    elif change == "role":
        who = identity(role="manager")
    elif change == "tool":
        tool = "search_maintenance_plans"
    elif change == "filter":
        args["filter"] = {"name": "alpha"}
    elif change == "tamper":
        args["cursor"] = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    elif change == "restart":
        reads = ReadTools(search_world)

    class NoDatabase:
        def transaction(self):
            raise AssertionError("Invalid cursor reached DB")

    reads.database = NoDatabase()
    with pytest.raises(ToolError) as caught:
        reads.run(who, tool, args)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "tool,args",
    [("search_equipment", {"page_size": value}) for value in [0, 101, True, "2", 1.5, None]]
    + [
        ("search_equipment", {"filter": None}),
        ("search_equipment", {"filter": {"name": 1}}),
        ("search_equipment", {"filter": {"sql": "SELECT 1"}}),
        ("search_equipment", {"role": "manager"}),
        ("search_equipment", {"cursor": "not-signed"}),
        ("search_equipment", {"cursor": ""}),
        ("search_equipment", {"cursor": "x" * 2049}),
        ("search_maintenance_plans", {"filter": {"equipment_id": None}}),
        ("search_maintenance_plans", {"filter": {"plan_status": "DONE"}}),
        ("search_maintenance_records", {"filter": {"equipment_id": "bad"}}),
        ("search_dependency_relations", {"filter": {"active": "false"}}),
        ("search_dependency_relations", {"filter": {"relation_type": "USES"}}),
        (
            "search_dependency_relations",
            {"filter": {"source": {"entity_type": "Bad", "entity_id": str(uuid4())}}},
        ),
        (
            "search_dependency_relations",
            {
                "filter": {
                    "target": {
                        "entity_type": "Equipment",
                        "entity_id": str(uuid4()),
                        "role": "manager",
                    }
                }
            },
        ),
    ],
)
def test_invalid_search_schema_before_database(tool, args):
    class NoDatabase:
        def transaction(self):
            raise AssertionError("Invalid input reached DB")

    with pytest.raises(ToolError) as caught:
        ReadTools(NoDatabase()).run(identity(), tool, args)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.integration
def test_search_does_not_mutate_any_table(search_world):
    def snapshot():
        with search_world.transaction() as c:
            tables = c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
            ).fetchall()
            return {
                row["tablename"]: c.execute(
                    sql.SQL(
                        "SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text"
                    ).format(sql.Identifier(row["tablename"]))
                ).fetchall()
                for row in tables
            }

    before = snapshot()
    reads = ReadTools(search_world)
    for tool in SEARCH_TOOLS:
        reads.run(identity(), tool, {"page_size": 1})
    assert snapshot() == before


@pytest.mark.integration
def test_cursor_uses_normalized_filter_and_distinguishes_explicit_null(search_world):
    reads = ReadTools(search_world)
    first = reads.run(
        identity(),
        "search_maintenance_records",
        {
            "filter": {"maintenance_plan_id": None, "equipment_id": str(UUID(int=1))},
            "page_size": 1,
        },
    )
    cursor = first.data["next_cursor"]
    second = reads.run(
        identity(),
        "search_maintenance_records",
        {
            "filter": {"equipment_id": "{" + str(UUID(int=1)) + "}", "maintenance_plan_id": None},
            "cursor": cursor,
        },
    )
    assert [row["maintenance_record_id"] for row in second.data["items"]] == [str(UUID(int=23))]
    with pytest.raises(ToolError) as caught:
        reads.run(
            identity(),
            "search_maintenance_records",
            {
                "filter": {"equipment_id": str(UUID(int=1))},
                "cursor": cursor,
            },
        )
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.integration
@pytest.mark.parametrize("field", ["name", "equipment_code"])
@pytest.mark.parametrize("payload", ["' OR 1=1 --", "'; DROP TABLE equipment; --", "日本語 %_"])
def test_core_equipment_search_binds_and_round_trips_text(search_world, field, payload):
    from linescope.core_reads import search_equipment_rows

    calls = []

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params):
            calls.append((query, params))
            return self.connection.execute(query, params)

    with search_world.transaction() as c:
        column = "equipment_name" if field == "name" else "equipment_code"
        c.execute(
            sql.SQL("UPDATE equipment SET {}=%s WHERE equipment_id=%s").format(
                sql.Identifier(column)
            ),
            (payload, UUID(int=4)),
        )
        rows = search_equipment_rows(RecordingConnection(c), {field: payload}, 2, None)
        assert [row["equipment_id"] for row in rows] == [UUID(int=4)]
        assert rows[0][column] == payload
        assert c.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 5
    assert len(calls) == 1
    query, params = calls[0]
    assert payload not in query
    assert payload in params.values()


@pytest.mark.integration
@pytest.mark.parametrize(
    "filters,after",
    [({}, UUID(int=2)), ({"name": "missing"}, None), ({"equipment_code": "missing"}, None)],
)
def test_core_equipment_page_native_rows_and_empty_observation(search_world, filters, after):
    from linescope.core_reads import search_equipment_rows

    with search_world.transaction() as c:
        rows = search_equipment_rows(c, filters, 2, after)
        assert len({row["_observed_at"] for row in rows}) == 1
        assert rows[0]["_observed_at"].tzinfo is not None
        if filters:
            assert len(rows) == 1
            assert rows[0]["equipment_id"] is None
        else:
            expected = c.execute(
                "SELECT * FROM equipment WHERE equipment_id>%s ORDER BY equipment_id LIMIT 3",
                (after,),
            ).fetchall()
            assert [
                {key: value for key, value in row.items() if key != "_observed_at"} for row in rows
            ] == expected
            assert rows[-1]["active"] is False


@pytest.mark.integration
@pytest.mark.parametrize("tool", SEARCH_TOOLS)
def test_core_search_keeps_readonly_transaction(search_world, tool):
    from contextlib import contextmanager

    import psycopg

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
                    self.connection.execute("UPDATE equipment SET active=false")
                checked.append(True)
            return result

    class GuardedDatabase:
        @contextmanager
        def transaction(self):
            with search_world.transaction() as connection:
                yield GuardedConnection(connection)

    result = ReadTools(GuardedDatabase()).run(identity(), tool, {"page_size": 2})
    assert checked == [True]
    assert len(result.data["items"]) == 2
    assert (result.data["next_cursor"] is not None) == (
        tool in {"search_equipment", "search_maintenance_records"}
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "tool,field,identifier",
    [
        ("search_maintenance_plans", "plan_code", UUID(int=11)),
        ("search_maintenance_records", "record_code", UUID(int=21)),
    ],
)
@pytest.mark.parametrize("payload", ["' OR 1=1 --", "'; DROP TABLE equipment; -- 日本語 %_"])
def test_core_remaining_search_text_bind_and_saved_value(
    search_world, tool, field, identifier, payload
):
    from linescope.core_reads import search_rows

    calls = []

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params):
            calls.append((query, params))
            return self.connection.execute(query, params)

    table, key, _ = SEARCH_TOOLS[tool]
    with search_world.transaction() as c:
        c.execute(
            sql.SQL("UPDATE {} SET {}=%s WHERE {}=%s").format(
                sql.Identifier(table), sql.Identifier(field), sql.Identifier(key)
            ),
            (payload, identifier),
        )
        rows = search_rows(RecordingConnection(c), tool, {field: payload}, 1, None)
        assert [row[key] for row in rows] == [identifier]
        assert rows[0][field] == payload
        assert c.execute("SELECT count(*) AS n FROM equipment").fetchone()["n"] == 5
    assert len(calls) == 1
    query, params = calls[0]
    assert payload not in query and payload in params.values()


@pytest.mark.integration
@pytest.mark.parametrize(
    "tool,first",
    [
        ("search_maintenance_plans", UUID(int=11)),
        ("search_maintenance_records", UUID(int=21)),
        ("search_dependency_relations", UUID(int=31)),
    ],
)
@pytest.mark.parametrize("use_after", [False, True])
def test_core_remaining_search_native_rows_keyset_and_transaction(
    search_world, tool, first, use_after
):
    from linescope.core_reads import search_rows

    table, key, _ = SEARCH_TOOLS[tool]
    after = first if use_after else None
    with search_world.transaction() as c:
        c.execute(sql.SQL("UPDATE {} SET version=99").format(sql.Identifier(table)))
        expected = c.execute(
            sql.SQL(
                "SELECT * FROM {} WHERE (%s::uuid IS NULL OR {}>%s) ORDER BY {} LIMIT 2"
            ).format(sql.Identifier(table), sql.Identifier(key), sql.Identifier(key)),
            (after, after),
        ).fetchall()
        rows = search_rows(c, tool, {}, 1, after)
        assert [
            {field: value for field, value in row.items() if field != "_observed_at"}
            for row in rows
        ] == expected
        assert len({row["_observed_at"] for row in rows}) == 1
        assert rows[0]["_observed_at"].tzinfo is not None
        assert all(row["version"] == 99 for row in rows)
        assert c.execute("SELECT 1 AS n").fetchone()["n"] == 1


@pytest.mark.integration
def test_core_relation_endpoints_and_false_use_bound_values(search_world):
    from linescope.core_reads import search_rows

    calls = []

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params):
            calls.append((query, params))
            return self.connection.execute(query, params)

    with search_world.transaction() as c:
        rows = search_rows(
            RecordingConnection(c),
            "search_dependency_relations",
            {
                "source": {"entity_type": "Equipment", "entity_id": UUID(int=1)},
                "target": {"entity_type": "Equipment", "entity_id": UUID(int=3)},
                "active": False,
            },
            1,
            None,
        )
        assert [row["dependency_relation_id"] for row in rows] == [UUID(int=32)]
    query, params = calls[0]
    assert any(value is False for value in params.values())
    assert UUID(int=1) in params.values() and UUID(int=3) in params.values()
    assert "Equipment" not in query
