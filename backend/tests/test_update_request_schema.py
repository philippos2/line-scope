from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from linescope.canonical import canonical_hash
from linescope.execution import ExecutionContext
from linescope.snapshot import build_equipment_state_snapshot, equipment_state_target

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def store(db):
    db.migrate()
    return db


def proposal():
    return build_equipment_state_snapshot(
        ExecutionContext("floor1", "floor", uuid4()),
        [
            equipment_state_target(
                {
                    "equipment_id": str(UUID(int=1)),
                    "state_code": "RUNNING",
                    "version": 1,
                },
                "STOPPED",
            )
        ],
    )


def insert_request(connection, **changes):
    snapshot = proposal()
    row = {
        "update_request_id": uuid4(),
        "requester_id": "floor1",
        "operation_type": "UPDATE",
        "status": "WAITING_APPROVAL",
        "idempotency_key": uuid4(),
        "prepare_retry_key": uuid4(),
        "prepare_input_hash": canonical_hash(
            {"equipment_id": str(UUID(int=1)), "state_code": "STOPPED"}
        ),
        "agent_input_hash": canonical_hash({"message": "Stop equipment"}),
        "canonical_snapshot": snapshot.canonical_text,
        "snapshot_schema_version": 1,
        "snapshot_hash": snapshot.snapshot_hash,
        "execution_result": None,
        **changes,
    }
    connection.execute(
        "INSERT INTO update_request(update_request_id,requester_id,operation_type,status,"
        "idempotency_key,prepare_retry_key,prepare_input_hash,agent_input_hash,canonical_snapshot,"
        "snapshot_schema_version,snapshot_hash,execution_result) VALUES("
        "%(update_request_id)s,%(requester_id)s,%(operation_type)s,%(status)s,"
        "%(idempotency_key)s,%(prepare_retry_key)s,%(prepare_input_hash)s,%(agent_input_hash)s,"
        "%(canonical_snapshot)s,%(snapshot_schema_version)s,%(snapshot_hash)s,%(execution_result)s)",
        row,
    )
    return row


def insert_target(connection, request_id, **changes):
    target = proposal().data["targets"][0]
    row = {
        "update_target_id": uuid4(),
        "update_request_id": request_id,
        "target_type": target["target_type"],
        "target_id": UUID(target["target_id"]),
        "business_key": Jsonb(target["business_key"]),
        "operation_type": "UPDATE",
        "before_snapshot": Jsonb(target["before"]),
        "proposed_snapshot": Jsonb(target["after"]),
        "expected_version": 1,
        **changes,
    }
    connection.execute(
        "INSERT INTO update_target(update_target_id,update_request_id,target_type,target_id,"
        "business_key,operation_type,before_snapshot,proposed_snapshot,expected_version) VALUES("
        "%(update_target_id)s,%(update_request_id)s,%(target_type)s,%(target_id)s,%(business_key)s,"
        "%(operation_type)s,%(before_snapshot)s,%(proposed_snapshot)s,%(expected_version)s)",
        row,
    )
    return row


def insert_approval(connection, request_id, **changes):
    row = {
        "approval_id": uuid4(),
        "update_request_id": request_id,
        "approver_id": None,
        "status": "PENDING",
        "snapshot_hash": proposal().snapshot_hash,
        "approved_at": None,
        "expires_at": None,
        "consumed_at": None,
        **changes,
    }
    connection.execute(
        "INSERT INTO approval(approval_id,update_request_id,approver_id,status,snapshot_hash,"
        "approved_at,expires_at,consumed_at) VALUES(%(approval_id)s,%(update_request_id)s,"
        "%(approver_id)s,%(status)s,%(snapshot_hash)s,%(approved_at)s,%(expires_at)s,%(consumed_at)s)",
        row,
    )
    return row


def test_upgrade_preserves_business_rows_and_packaged_migration(db):
    from importlib.resources import files

    root = files("linescope").joinpath("migrations")
    db.migrate(
        [
            (name, root.joinpath(name).read_text())
            for name in ["001_bootstrap.sql", "002_business_schema.sql"]
        ]
    )
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) "
            "VALUES(%s,'EQ1','Equipment','machine',true)",
            (UUID(int=1),),
        )
    assert db.migrate() == [
        "003_update_request_schema.sql",
        "004_update_audit_events.sql",
        "005_execution_history.sql",
    ]
    assert db.migrate() == []
    with db.transaction() as connection:
        assert connection.execute("SELECT version FROM equipment").fetchone()["version"] == 1
        insert_request(connection)


def test_request_target_approval_commit_and_snapshot_round_trip(store):
    with store.transaction() as connection:
        request = insert_request(connection)
        insert_target(connection, request["update_request_id"])
        insert_approval(connection, request["update_request_id"])
    with store.transaction() as connection:
        saved = connection.execute(
            "SELECT r.canonical_snapshot,r.snapshot_hash,r.created_at,r.execution_result,"
            "t.before_snapshot,t.proposed_snapshot,t.expected_version,a.status,a.expires_at "
            "FROM update_request r JOIN update_target t USING(update_request_id) "
            "JOIN approval a USING(update_request_id)"
        ).fetchone()
        assert saved["canonical_snapshot"] == proposal().canonical_text
        assert saved["snapshot_hash"] == canonical_hash(proposal().data)
        assert saved["expected_version"] == saved["before_snapshot"]["version"] == 1
        assert saved["proposed_snapshot"]["version"] == 2
        assert saved["status"] == "PENDING" and saved["expires_at"] is None
        assert saved["execution_result"] is None
        assert saved["created_at"].tzinfo is not None


def test_failed_prepare_storage_rolls_back_entire_bundle(store):
    with pytest.raises(psycopg.errors.UniqueViolation), store.transaction() as connection:
        request = insert_request(connection)
        insert_target(connection, request["update_request_id"])
        insert_approval(connection, request["update_request_id"])
        insert_approval(connection, request["update_request_id"])
    with store.transaction() as connection:
        counts = connection.execute(
            "SELECT (SELECT count(*) FROM update_request) AS requests,"
            "(SELECT count(*) FROM update_target) AS targets,"
            "(SELECT count(*) FROM approval) AS approvals"
        ).fetchone()
        assert counts == {"requests": 0, "targets": 0, "approvals": 0}


def test_retry_key_owner_scope_and_terminal_retention(store):
    retry_key = uuid4()
    with store.transaction() as connection:
        insert_request(connection, prepare_retry_key=retry_key, status="REJECTED")
        insert_request(connection, prepare_retry_key=retry_key, requester_id="manager1")
    with pytest.raises(psycopg.errors.UniqueViolation), store.transaction() as connection:
        insert_request(connection, prepare_retry_key=retry_key)


def test_concurrent_same_owner_retry_key_accepts_exactly_one_row(store):
    retry_key, barrier = uuid4(), Barrier(2)

    def submit():
        try:
            with store.transaction() as connection:
                barrier.wait(timeout=5)
                insert_request(connection, prepare_retry_key=retry_key)
            return "saved"
        except psycopg.errors.UniqueViolation:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: submit(), range(2))) == ["duplicate", "saved"]
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 1


def test_idempotency_key_is_globally_unique(store):
    key = uuid4()
    with store.transaction() as connection:
        insert_request(connection, idempotency_key=key)
    with pytest.raises(psycopg.errors.UniqueViolation), store.transaction() as connection:
        insert_request(connection, idempotency_key=key, requester_id="manager1")


@pytest.mark.parametrize(
    "changes",
    [
        {"requester_id": " "},
        {"operation_type": "DELETE"},
        {"status": "PENDING"},
        {"snapshot_schema_version": 2},
        {"snapshot_hash": "g" * 64},
        {"prepare_input_hash": "A" * 64},
        {"agent_input_hash": "short"},
        {"canonical_snapshot": ""},
        {"status": "COMPLETED"},
        {"execution_result": Jsonb({"committed": True})},
        {"status": "COMPLETED", "execution_result": Jsonb([])},
        {"status": "COMPLETED", "execution_result": Jsonb(None)},
    ],
)
def test_invalid_request_or_completion_result_rejected(store, changes):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        insert_request(connection, **changes)


def test_completed_result_storage(store):
    with store.transaction() as connection:
        saved = insert_request(
            connection,
            status="COMPLETED",
            execution_result=Jsonb({"after_snapshot": proposal().data}),
        )
        result = connection.execute(
            "SELECT execution_result FROM update_request WHERE update_request_id=%s",
            (saved["update_request_id"],),
        ).fetchone()["execution_result"]
        assert result["after_snapshot"] == proposal().data


@pytest.mark.parametrize("insert", [insert_target, insert_approval])
def test_orphan_related_rows_rejected(store, insert):
    with pytest.raises(psycopg.errors.ForeignKeyViolation), store.transaction() as connection:
        insert(connection, uuid4())


def test_parent_deletion_rejected_while_targets_and_approval_exist(store):
    with store.transaction() as connection:
        request = insert_request(connection)
        insert_target(connection, request["update_request_id"])
        insert_approval(connection, request["update_request_id"])
    with pytest.raises(psycopg.errors.ForeignKeyViolation), store.transaction() as connection:
        connection.execute(
            "DELETE FROM update_request WHERE update_request_id=%s", (request["update_request_id"],)
        )


@pytest.mark.parametrize("kind", ["identity", "business_key"])
def test_duplicate_target_or_business_key_rejected(store, kind):
    with pytest.raises(psycopg.errors.UniqueViolation), store.transaction() as connection:
        request = insert_request(connection)
        insert_target(connection, request["update_request_id"])
        changes = (
            {"target_id": uuid4()}
            if kind == "business_key"
            else {
                "business_key": Jsonb({"equipment_id": str(uuid4())}),
            }
        )
        insert_target(connection, request["update_request_id"], **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"target_type": "Equipment"},
        {"operation_type": "CREATE"},
        {"operation_type": "DELETE"},
        {"expected_version": None},
        {"expected_version": 0},
        {"before_snapshot": None},
        {"before_snapshot": Jsonb(None)},
        {"before_snapshot": Jsonb([])},
        {"proposed_snapshot": Jsonb(None)},
        {"business_key": Jsonb([])},
        {"target_type": "MaintenanceRecord"},
        {"target_type": "MaintenancePlan", "operation_type": "DISABLE"},
    ],
)
def test_invalid_target_operation_or_version_shape_rejected(store, changes):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        request = insert_request(connection)
        insert_target(connection, request["update_request_id"], **changes)


def test_create_target_requires_sql_null_before_and_expected_version(store):
    with store.transaction() as connection:
        request = insert_request(connection, operation_type="CREATE")
        insert_target(
            connection,
            request["update_request_id"],
            target_type="MaintenanceRecord",
            operation_type="CREATE",
            before_snapshot=None,
            expected_version=None,
        )
    for changes in [{"before_snapshot": Jsonb(None)}, {"expected_version": 1}]:
        with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
            request = insert_request(connection, operation_type="CREATE")
            args = {
                "target_type": "MaintenanceRecord",
                "operation_type": "CREATE",
                "before_snapshot": None,
                "expected_version": None,
                **changes,
            }
            insert_target(connection, request["update_request_id"], **args)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "COMPLETED"},
        {"snapshot_hash": "x" * 64},
        {"approver_id": " "},
        {"status": "APPROVED"},
        {"status": "EXPIRED"},
        {"status": "REJECTED"},
        {"approved_at": NOW},
        {"expires_at": NOW},
        {"consumed_at": NOW},
        {"approver_id": "manager1"},
    ],
)
def test_invalid_pending_or_missing_approval_metadata_rejected(store, changes):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        request = insert_request(connection)
        insert_approval(connection, request["update_request_id"], **changes)


@pytest.mark.parametrize("delta", [timedelta(minutes=29), timedelta(minutes=31), timedelta(0)])
def test_approval_expiry_is_exactly_thirty_minutes(store, delta):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        request = insert_request(connection)
        insert_approval(
            connection,
            request["update_request_id"],
            status="APPROVED",
            approver_id="manager1",
            approved_at=NOW,
            expires_at=NOW + delta,
        )


@pytest.mark.parametrize(
    "offset", [timedelta(seconds=-1), timedelta(minutes=30), timedelta(minutes=31)]
)
def test_consumed_timestamp_must_be_inside_approval_window(store, offset):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        request = insert_request(connection)
        insert_approval(
            connection,
            request["update_request_id"],
            status="CONSUMED",
            approver_id="manager1",
            approved_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
            consumed_at=NOW + offset,
        )


def test_valid_approval_metadata_states_can_be_stored(store):
    for state in ["APPROVED", "CONSUMED", "EXPIRED", "INVALIDATED", "REJECTED"]:
        with store.transaction() as connection:
            request = insert_request(connection)
            fields = {"status": state, "approver_id": "manager1"}
            if state != "REJECTED":
                fields.update(approved_at=NOW, expires_at=NOW + timedelta(minutes=30))
            if state == "CONSUMED":
                fields["consumed_at"] = NOW + timedelta(seconds=1)
            insert_approval(connection, request["update_request_id"], **fields)
