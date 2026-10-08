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
