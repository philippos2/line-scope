from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

TABLES = {
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
}
START = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def business(db):
    db.migrate()
    equipment, process, operation = uuid4(), uuid4(), uuid4()
    with db.transaction() as c:
        c.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,"
            "equipment_type,active) VALUES(%s,'EQ1','Equipment','machine',true)",
            (equipment,),
        )
        c.execute(
            "INSERT INTO process(process_id,process_code,process_name,active) "
            "VALUES(%s,'P1','Process',true)",
            (process,),
        )
        c.execute(
            "INSERT INTO production_operation(production_operation_id,operation_code,"
            "process_id,planned_status,planned_start,planned_end,active) "
            "VALUES(%s,'OP1',%s,'PLANNED',%s,%s,true)",
            (operation, process, START, START + timedelta(hours=1)),
        )
    return db, equipment, operation


@pytest.mark.integration
def test_schema_boundary_and_upgrade_from_foundation(db):
    from importlib.resources import files

    root = files("linescope").joinpath("migrations")
    db.migrate([("001_bootstrap.sql", root.joinpath("001_bootstrap.sql").read_text())])
    assert db.migrate() == [
        "002_business_schema.sql",
        "003_update_request_schema.sql",
        "004_update_audit_events.sql",
        "005_execution_history.sql",
        "006_graph_projection_storage.sql",
    ]
    assert db.migrate() == []
    with db.transaction() as c:
        tables = c.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
        ).fetchall()
        assert {row["tablename"] for row in tables} == TABLES | {
            "schema_migration",
            "update_request",
            "update_target",
            "approval",
            "update_audit_event",
            "business_update_history",
            "equipment_state_history",
            "graph_outbox",
            "graph_projection_control",
        }
        columns = c.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='production_operation'"
        ).fetchall()
        assert "assigned_equipment_id" not in {row["column_name"] for row in columns}


@pytest.mark.integration
@pytest.mark.parametrize("state", ["RUNNING", "STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"])
def test_equipment_states_and_initial_version(business, state):
    db, equipment, _ = business
    with db.transaction() as c:
        row = c.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) "
            "VALUES(%s,%s) RETURNING version",
            (equipment, state),
        ).fetchone()
        assert row["version"] == 1


@pytest.mark.integration
@pytest.mark.parametrize("value", ["BROKEN", None])
def test_invalid_state_rejected(business, value):
    db, equipment, _ = business
    with pytest.raises(psycopg.IntegrityError), db.transaction() as c:
        c.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,%s)",
            (equipment, value),
        )


@pytest.mark.integration
@pytest.mark.parametrize("version", [0, -1, None])
def test_invalid_version_rejected(business, version):
    db, equipment, _ = business
    with pytest.raises(psycopg.IntegrityError), db.transaction() as c:
        c.execute("UPDATE equipment SET version=%s WHERE equipment_id=%s", (version, equipment))


@pytest.mark.integration
def test_unique_business_key_and_fk(business):
    db, _, _ = business
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        c.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,"
            "equipment_type,active) VALUES(%s,'EQ1','Duplicate','machine',true)",
            (uuid4(),),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction() as c:
        c.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'UNKNOWN')",
            (uuid4(),),
        )


@pytest.mark.integration
@pytest.mark.parametrize("end", [START, START - timedelta(seconds=1)])
def test_invalid_assignment_period_rejected(business, end):
    db, equipment, operation = business
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment "
            "(assignment_id,production_operation_id,equipment_id,effective_from,"
            "effective_to,active) VALUES(%s,%s,%s,%s,%s,true)",
            (uuid4(), operation, equipment, START, end),
        )


@pytest.mark.integration
def test_assignment_nullable_end_and_deferred_key_swap(business):
    db, equipment, operation = business
    ids = [uuid4(), uuid4()]
    later = START + timedelta(hours=1)
    with db.transaction() as c:
        for identifier, start, end in [(ids[0], START, later), (ids[1], later, None)]:
            c.execute(
                "INSERT INTO production_operation_equipment_assignment "
                "(assignment_id,production_operation_id,equipment_id,effective_from,"
                "effective_to,active) VALUES(%s,%s,%s,%s,%s,true)",
                (identifier, operation, equipment, start, end),
            )
        c.execute("SET CONSTRAINTS ALL DEFERRED")
        c.execute(
            "UPDATE production_operation_equipment_assignment "
            "SET effective_from=%s,effective_to=NULL WHERE assignment_id=%s",
            (later, ids[0]),
        )
        c.execute(
            "UPDATE production_operation_equipment_assignment "
            "SET effective_from=%s,effective_to=%s WHERE assignment_id=%s",
            (START, later, ids[1]),
        )
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        c.execute(
            "INSERT INTO production_operation_equipment_assignment "
            "(assignment_id,production_operation_id,equipment_id,effective_from,active) "
            "VALUES(%s,%s,%s,%s,false)",
            (uuid4(), operation, equipment, START),
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind,source,target,required",
    [
        ("USES", "ProductionOperation", "Equipment", False),
        ("PRECEDES", "Process", "ProductionOperation", False),
        ("CAN_SUBSTITUTE", "Equipment", "Process", False),
        ("CONTROLS", "Equipment", "Equipment", True),
        ("DEPENDS_ON", "Product", "Equipment", True),
    ],
)
def test_invalid_relation_contract_rejected(business, kind, source, target, required):
    db, equipment, _ = business
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction() as c:
        c.execute(
            "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,"
            "source_entity_id,target_entity_type,target_entity_id,relation_type,"
            "effective_from,required,active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,true)",
            (uuid4(), source, equipment, target, uuid4(), kind, START, required),
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "status,end,result",
    [
        ("DONE", START + timedelta(hours=1), "done"),
        ("PLANNED", START, "done"),
        ("PLANNED", START + timedelta(hours=1), "   "),
    ],
)
def test_maintenance_input_constraints(business, status, end, result):
    db, equipment, _ = business
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction() as c:
        c.execute(
            "INSERT INTO maintenance_plan(maintenance_plan_id,plan_code,equipment_id,"
            "planned_start,planned_end,plan_status) VALUES(%s,'MP1',%s,%s,%s,%s)",
            (uuid4(), equipment, START, end, status),
        )
        c.execute(
            "INSERT INTO maintenance_record(maintenance_record_id,record_code,"
            "equipment_id,performed_at,result) VALUES(%s,'MR1',%s,%s,%s)",
            (uuid4(), equipment, START, result),
        )


@pytest.mark.integration
def test_maintenance_record_does_not_change_equipment_or_schedule(business):
    db, equipment, operation = business
    with db.transaction() as c:
        c.execute(
            "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,'STOPPED')",
            (equipment,),
        )
        c.execute(
            "INSERT INTO maintenance_record(maintenance_record_id,record_code,"
            "equipment_id,performed_at,result) VALUES(%s,'MR1',%s,%s,'Completed')",
            (uuid4(), equipment, START),
        )
        assert (
            c.execute(
                "SELECT state_code FROM equipment_current_state WHERE equipment_id=%s", (equipment,)
            ).fetchone()["state_code"]
            == "STOPPED"
        )
        assert (
            c.execute(
                "SELECT planned_status FROM production_operation WHERE production_operation_id=%s",
                (operation,),
            ).fetchone()["planned_status"]
            == "PLANNED"
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind,source,target,required",
    [
        ("DEPENDS_ON", "Equipment", "InfrastructureResource", True),
        ("PRECEDES", "Process", "Process", False),
        ("SUPPLIES", "InfrastructureResource", "ProductionOperation", True),
        ("CONTROLS", "Equipment", "Equipment", False),
        ("PRODUCES", "ProductionOperation", "Product", False),
        ("CAN_SUBSTITUTE", "InfrastructureResource", "InfrastructureResource", False),
    ],
)
def test_valid_relation_types_and_business_key(business, kind, source, target, required):
    db, equipment, _ = business
    target_id = uuid4()
    values = (source, equipment, target, target_id, kind, START, required)
    statement = (
        "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,"
        "source_entity_id,target_entity_type,target_entity_id,relation_type,"
        "effective_from,required,active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,true)"
    )
    with db.transaction() as c:
        c.execute(statement, (uuid4(), *values))
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        c.execute(statement, (uuid4(), *values))
