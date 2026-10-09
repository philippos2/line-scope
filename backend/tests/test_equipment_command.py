import json
from uuid import uuid4

import pytest
from test_proposals import NOW, context

from linescope.agent_input import AgentInput
from linescope.demo_seed import DEMO_EQUIPMENT, seed_demo
from linescope.equipment_command import EquipmentCommandPrepare
from linescope.reads import ReadResult, ToolError
from linescope.update_intent import equipment_state_command


def incoming(owner, message="設備M-204の状態をRUNNINGに変更して", key=None, **fields):
    return AgentInput.parse(
        owner, json.dumps({"message": message, **fields}), received_at=NOW, idempotency_key=key
    )


@pytest.fixture
def world(db):
    db.migrate()
    seed_demo(db)
    return db


@pytest.mark.parametrize(
    "value,expected",
    [
        ("稼働中", "RUNNING"),
        ("停止", "STOPPED"),
        ("保全中", "UNDER_MAINTENANCE"),
        ("不明", "UNKNOWN"),
        ("RUNNING", "RUNNING"),
        ("STOPPED", "STOPPED"),
        ("UNDER_MAINTENANCE", "UNDER_MAINTENANCE"),
        ("UNKNOWN", "UNKNOWN"),
    ],
)
def test_command_values_come_from_original_permission_evidence(value, expected):
    owner = context()
    request = incoming(owner, f" 設備M-204の状態を{value}に更新してください。\n")
    command = equipment_state_command(request)
    assert command.equipment_code == "M-204" and command.state_code == expected
    assert command.intent.confirmed and command.intent.category == "EQUIPMENT_STATE"


@pytest.mark.parametrize(
    "message",
    [
        "M-204が故障した。影響を調べて",
        "設備M-204の状態をRUNNINGに変更しないで",
        "『設備M-204の状態をRUNNINGに変更して』",
        "設備M-204の状態をRUNNINGに変更して？",
        "設備M-204の状態をRUNNINGに変更して、M-208も変更して",
        "M-204の保全予定を登録して",
    ],
)
def test_unsupported_commands_never_access_database(message):
    class NoDatabase:
        def transaction(self):
            raise AssertionError("No database access is permitted")

    owner = context()
    request = incoming(owner, message)
    assert equipment_state_command(request) is None
    with pytest.raises(ToolError) as caught:
        EquipmentCommandPrepare(NoDatabase()).run(owner, request)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_prepare_binds_code_and_value_without_mutating_current_state(world):
    owner = context()
    saved = EquipmentCommandPrepare(world).run(owner, incoming(owner))
    target = saved.snapshot.data["targets"][0]
    assert target["before"]["equipment_id"] == str(DEMO_EQUIPMENT[0][0])
    assert target["before"]["state_code"] == "STOPPED"
    assert target["after"]["state_code"] == "RUNNING"
    assert target["expected_version"] == 1 and target["after"]["version"] == 2
    assert saved.status == "WAITING_APPROVAL" and saved.approval_status == "PENDING"
    with world.transaction() as connection:
        assert (
            connection.execute(
                "SELECT state_code FROM equipment_current_state WHERE equipment_id=%s",
                (DEMO_EQUIPMENT[0][0],),
            ).fetchone()["state_code"]
            == "STOPPED"
        )
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 1


def test_current_changes_do_not_change_replayed_snapshot(world):
    owner = context()
    request = incoming(owner, key=str(uuid4()))
    service = EquipmentCommandPrepare(world)
    saved = service.run(owner, request)
    with world.transaction() as connection:
        connection.execute("UPDATE equipment_current_state SET state_code='UNKNOWN',version=9")
        connection.execute(
            "UPDATE equipment SET equipment_code='RENAMED' WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        )
    replayed = service.run(owner, request)
    assert replayed.replayed and replayed.update_request_id == saved.update_request_id
    assert replayed.snapshot == saved.snapshot
    with pytest.raises(ToolError) as caught:
        service.run(owner, incoming(owner, "M-208の状態を停止に更新して", key=request.retry_key))
    assert caught.value.code == "DUPLICATE_REQUEST"


def test_permission_loss_prevents_replay(world):
    owner = context()
    request = incoming(owner)
    service = EquipmentCommandPrepare(world)
    service.run(owner, request)
    with pytest.raises(ToolError) as caught:
        service.run(context(user=owner.authenticated_user_id, role="production"), request)
    assert caught.value.code == "AUTHORIZATION_DENIED"


def test_unknown_code_does_not_create_request(world):
    owner = context()
    with pytest.raises(ToolError) as caught:
        EquipmentCommandPrepare(world).run(owner, incoming(owner, "M-999の状態を停止に変更して"))
    assert caught.value.code == "TARGET_NOT_FOUND"
    with world.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "fields", [{"context_id": str(uuid4())}, {"as_of": "2020-01-01T00:00:00Z"}]
)
def test_context_and_temporal_modes_are_not_silently_ignored(world, fields):
    owner = context()
    with pytest.raises(ToolError) as caught:
        EquipmentCommandPrepare(world).run(owner, incoming(owner, **fields))
    assert caught.value.code == "INVALID_ARGUMENT"


def test_ambiguous_search_result_is_never_used_to_prepare(world):
    class Ambiguous:
        def schemas(self):
            return {"search_equipment": {}, "prepare_equipment_state_update": {}}

        def run(self, owner, tool, args, **metadata):
            assert tool == "search_equipment"
            assert args["filter"] == {"equipment_code": "M-204"}
            return ReadResult(
                {"items": [{"equipment_id": str(uuid4())}] * 2, "next_cursor": None}, {}
            )

    service = EquipmentCommandPrepare(world)
    service.dispatcher = Ambiguous()
    owner = context()
    with pytest.raises(ToolError) as caught:
        service.run(owner, incoming(owner))
    assert caught.value.code == "TARGET_AMBIGUOUS"
