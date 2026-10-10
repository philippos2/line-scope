from importlib.resources import files
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_update_request_schema import insert_approval, insert_request

from linescope.demo_seed import DEMO_EQUIPMENT, seed_demo


def history(c, request, approval, **changes):
    row = dict(
        history_id=uuid4(),
        update_request_id=request["update_request_id"],
        approval_id=approval["approval_id"],
        requester_id="floor1",
        approver_id="approver",
        category="EQUIPMENT_STATE",
        before_snapshot=Jsonb({"state_code": "STOPPED"}),
        after_snapshot=Jsonb({"state_code": "RUNNING"}),
        result="OK",
    )
    row.update(changes)
    c.execute(
        "INSERT INTO business_update_history(history_id,update_request_id,approval_id,requester_id,approver_id,category,before_snapshot,after_snapshot,result,occurred_at) VALUES(%(history_id)s,%(update_request_id)s,%(approval_id)s,%(requester_id)s,%(approver_id)s,%(category)s,%(before_snapshot)s,%(after_snapshot)s,%(result)s,clock_timestamp())",
        row,
    )


@pytest.fixture
def saved(db):
    db.migrate()
    seed_demo(db)
    with db.transaction() as c:
        request = insert_request(c)
        approval = insert_approval(c, request["update_request_id"])
    return db, request, approval


def test_upgrade_preserves_pending_requests_without_fabricated_history(db):
    root = files("linescope").joinpath("migrations")
    db.migrate(
        [
            (p.name, p.read_text())
            for p in root.iterdir()
            if p.name.endswith(".sql") and p.name < "005"
        ]
    )
    seed_demo(db)
    with db.transaction() as c:
        request = insert_request(c)
        insert_approval(c, request["update_request_id"])
    assert db.migrate() == ["005_execution_history.sql", "006_graph_projection_storage.sql"]
    assert db.migrate() == []
    with db.transaction() as c:
        assert (
            c.execute("SELECT status FROM update_request").fetchone()["status"]
            == "WAITING_APPROVAL"
        )
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM equipment_state_history").fetchone()["n"] == 0


def test_one_business_history_per_request(saved):
    db, request, approval = saved
    with db.transaction() as c:
        history(c, request, approval)
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        history(c, request, approval)


def test_history_rejects_approval_of_another_request(saved):
    db, request, approval = saved
    with db.transaction() as c:
        other = insert_request(c)
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction() as c:
        history(c, other, approval)


@pytest.mark.parametrize(
    "changes",
    [{"requester_id": " "}, {"approver_id": ""}, {"category": "INVENTORY"}, {"result": ""}],
)
def test_invalid_history_metadata_is_rejected(saved, changes):
    db, request, approval = saved
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction() as c:
        history(c, request, approval, **changes)


def test_equipment_history_tracks_multiple_targets_and_rejects_duplicates(saved):
    db, request, _ = saved

    def insert(c, equipment, state="RUNNING"):
        c.execute(
            "INSERT INTO equipment_state_history(history_id,equipment_id,update_request_id,state_code,effective_at,recorded_at) VALUES(%s,%s,%s,%s,clock_timestamp(),clock_timestamp())",
            (uuid4(), equipment, request["update_request_id"], state),
        )

    with db.transaction() as c:
        for equipment in DEMO_EQUIPMENT:
            insert(c, equipment[0])
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction() as c:
        insert(c, DEMO_EQUIPMENT[0][0])
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction() as c:
        insert(c, DEMO_EQUIPMENT[0][0], "DEGRADED")


def test_history_insert_and_business_change_roll_back_together(saved):
    db, request, approval = saved
    with pytest.raises(RuntimeError), db.transaction() as c:
        c.execute(
            "UPDATE equipment_current_state SET state_code='RUNNING',version=2 WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        )
        history(c, request, approval)
        raise RuntimeError("rollback probe")
    with db.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM business_update_history").fetchone()["n"] == 0
        assert c.execute(
            "SELECT state_code,version FROM equipment_current_state WHERE equipment_id=%s",
            (DEMO_EQUIPMENT[0][0],),
        ).fetchone() == {"state_code": "STOPPED", "version": 1}
