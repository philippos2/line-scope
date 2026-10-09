from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from test_production_prepare import AGENT_HASH, END, START, counts, identity

from linescope.proposals import SavedProposal
from linescope.reads import ReadResult, ToolError
from linescope.tools import PREPARE_CATEGORIES, ToolDispatcher


@pytest.fixture
def database(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,'EQ','Machine','machine',true)",
            (UUID(int=100),),
        )
        connection.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code,version) VALUES(%s,'RUNNING',3)",
            (UUID(int=100),),
        )
        connection.execute(
            "INSERT INTO process(process_id,process_code,process_name,active) VALUES(%s,'P','Process',true)",
            (UUID(int=10),),
        )
        connection.execute(
            "INSERT INTO production_operation(production_operation_id,operation_code,process_id,planned_status,planned_start,planned_end,active,version) VALUES(%s,'OP',%s,'PLANNED',%s,%s,true,5)",
            (UUID(int=20), UUID(int=10), START, END),
        )
        connection.execute(
            "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,planned_start,planned_end,plan_status,version) VALUES(%s,'OLD',%s,%s,%s,'PLANNED',4)",
            (UUID(int=40), UUID(int=100), START, END),
        )
        connection.execute(
            "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,source_entity_id,target_entity_type,target_entity_id,relation_type,effective_from,effective_to,required,active,version) VALUES(%s,'Equipment',%s,'Process',%s,'DEPENDS_ON',%s,NULL,true,true,2)",
            (UUID(int=200), UUID(int=100), UUID(int=10), START),
        )
    return db


def inputs():
    return {
        "prepare_equipment_state_update": {
            "equipment_id": str(UUID(int=100)),
            "state_code": "STOPPED",
        },
        "prepare_maintenance_plan_create": {
            "plan_code": "NEW",
            "equipment_id": str(UUID(int=100)),
            "planned_start": START,
            "planned_end": END,
            "plan_status": "PLANNED",
        },
        "prepare_maintenance_plan_update": {
            "maintenance_plan_id": str(UUID(int=40)),
            "patch": {"plan_status": "CANCELLED"},
        },
        "prepare_maintenance_record_create": {
            "record_code": "REC",
            "equipment_id": str(UUID(int=100)),
            "performed_at": START,
            "result": "Inspected",
        },
        "prepare_production_operation_update": {
            "production_operation_id": str(UUID(int=20)),
            "patch": {"planned_status": "CANCELLED"},
        },
        "prepare_dependency_relation_update": {
            "operation_type": "UPDATE",
            "dependency_relation_id": str(UUID(int=200)),
            "patch": {"required": False},
        },
    }


def run(dispatcher, tool, arguments, **kwargs):
    return dispatcher.run(
        kwargs.pop("context", identity("manager")),
        tool,
        arguments,
        retry_key=kwargs.pop("key", uuid4()),
        agent_input_hash=AGENT_HASH,
        **kwargs,
    )


@pytest.mark.parametrize("tool", list(PREPARE_CATEGORIES))
def test_each_single_prepare_routes_to_real_service(database, tool):
    result = run(ToolDispatcher(database), tool, inputs()[tool])
    assert isinstance(result, SavedProposal) and result.status == "WAITING_APPROVAL"
    assert counts(database)["requests"] == 1
    with database.transaction() as connection:
        assert (
            connection.execute("SELECT state_code FROM equipment_current_state").fetchone()[
                "state_code"
            ]
            == "RUNNING"
        )
        assert connection.execute("SELECT count(*) AS n FROM maintenance_plan").fetchone()["n"] == 1
        assert (
            connection.execute("SELECT count(*) AS n FROM maintenance_record").fetchone()["n"] == 0
        )
        assert (
            connection.execute("SELECT version FROM dependency_relation").fetchone()["version"] == 2
        )


def test_real_read_and_prepare_types_and_read_nonmutation(database):
    dispatcher = ToolDispatcher(database)
    result = dispatcher.run(
        identity("floor"), "get_equipment", {"equipment_id": str(UUID(int=100))}
    )
    assert isinstance(result, ReadResult)
    assert counts(database)["requests"] == 0
    assert result.evidence["source"] == "POSTGRESQL"


def test_mixed_maintenance_targets_and_retry_match_single_form(database):
    dispatcher = ToolDispatcher(database)
    first_tool = "prepare_maintenance_plan_update"
    args = {
        "targets": [
            {"prepare_tool": first_tool, "input": inputs()[first_tool]},
            {
                "prepare_tool": "prepare_maintenance_record_create",
                "input": inputs()["prepare_maintenance_record_create"],
            },
        ]
    }
    saved = run(dispatcher, first_tool, args)
    assert len(saved.snapshot.data["targets"]) == 2 and saved.operation_type == "COMPOSITE"
    key = uuid4()
    tool = "prepare_equipment_state_update"
    first = run(dispatcher, tool, inputs()[tool], key=key)
    second = run(
        dispatcher, tool, {"targets": [{"prepare_tool": tool, "input": inputs()[tool]}]}, key=key
    )
    assert second.replayed and first.snapshot == second.snapshot


class NoDatabase:
    def transaction(self):
        pytest.fail("Rejected dispatch touched database")


@pytest.mark.parametrize(
    "tool",
    [
        "approve",
        "execute",
        "reject",
        "execute_update_request",
        "cypher",
        "sql",
        "trace_downstream_impact",
        "search_knowledge",
    ],
)
def test_unregistered_tools_never_run(tool):
    with pytest.raises(ToolError) as caught:
        run(ToolDispatcher(NoDatabase()), tool, {})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        [],
        {"targets": []},
        {"targets": None},
        {"targets": [None]},
        {"targets": [{"prepare_tool": "unknown", "input": {}}]},
        {"targets": [{"prepare_tool": [], "input": {}}]},
        {"targets": [{"prepare_tool": "prepare_equipment_state_update", "input": None}]},
        {
            "targets": [
                {"prepare_tool": "prepare_equipment_state_update", "input": {}, "role": "manager"}
            ]
        },
        {
            "targets": [{"prepare_tool": "prepare_equipment_state_update", "input": {}}],
            "equipment_id": str(UUID(int=100)),
        },
    ],
)
def test_malformed_wrapper_rejected_before_db(arguments):
    with pytest.raises(ToolError) as caught:
        run(ToolDispatcher(NoDatabase()), "prepare_equipment_state_update", arguments)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_first_tool_must_match_called_name():
    with pytest.raises(ToolError) as caught:
        run(
            ToolDispatcher(NoDatabase()),
            "prepare_maintenance_plan_update",
            {
                "targets": [
                    {
                        "prepare_tool": "prepare_maintenance_plan_create",
                        "input": inputs()["prepare_maintenance_plan_create"],
                    }
                ]
            },
        )
    assert caught.value.code == "INVALID_ARGUMENT"


def test_cross_category_rejected_before_any_save():
    values = inputs()
    with pytest.raises(ToolError) as caught:
        run(
            ToolDispatcher(NoDatabase()),
            "prepare_equipment_state_update",
            {
                "targets": [
                    {
                        "prepare_tool": "prepare_equipment_state_update",
                        "input": values["prepare_equipment_state_update"],
                    },
                    {
                        "prepare_tool": "prepare_maintenance_plan_update",
                        "input": values["prepare_maintenance_plan_update"],
                    },
                ]
            },
        )
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"


@pytest.mark.parametrize(
    "field",
    [
        "role",
        "user_id",
        "retry_key",
        "agent_input_hash",
        "supersedes_update_request_id",
        "expected_version",
    ],
)
def test_tool_arguments_cannot_inject_trusted_metadata(field):
    value = {**inputs()["prepare_equipment_state_update"], field: "forged"}
    with pytest.raises(ToolError) as caught:
        run(ToolDispatcher(NoDatabase()), "prepare_equipment_state_update", value)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_authentication_before_tool_lookup():
    with pytest.raises(ToolError) as caught:
        run(ToolDispatcher(NoDatabase()), "execute", {}, context=object())
    assert caught.value.code == "AUTHENTICATION_REQUIRED"


def test_prepare_permission_and_error_code_preserved():
    with pytest.raises(ToolError) as caught:
        run(
            ToolDispatcher(NoDatabase()),
            "prepare_dependency_relation_update",
            inputs()["prepare_dependency_relation_update"],
            context=identity("floor"),
        )
    assert caught.value.code == "AUTHORIZATION_DENIED" and caught.value.details == {}


def test_schemas_include_only_implemented_tools_and_no_trusted_metadata():
    dispatcher = ToolDispatcher(NoDatabase())
    schemas = dispatcher.schemas()
    assert len(schemas) == 19
    assert set(PREPARE_CATEGORIES) <= schemas.keys()
    assert "execute" not in schemas and "trace_downstream_impact" not in schemas
    for tool in PREPARE_CATEGORIES:
        schema = schemas[tool]
        assert len(schema["oneOf"]) == 2
        multi = schema["oneOf"][1]
        assert multi["additionalProperties"] is False and multi["required"] == ["targets"]
        assert multi["properties"]["targets"]["minItems"] == 1
        names = {
            item["properties"]["prepare_tool"]["const"]
            for item in multi["properties"]["targets"]["items"]["oneOf"]
        }
        assert names == {
            name
            for name, category in PREPARE_CATEGORIES.items()
            if category == PREPARE_CATEGORIES[tool]
        }
    before = deepcopy(schemas)
    schemas["prepare_equipment_state_update"]["oneOf"][0]["properties"]["equipment_id"]["type"] = (
        "number"
    )
    assert dispatcher.schemas() == before
