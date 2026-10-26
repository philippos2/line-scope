"""Ten approved identity partitions, using the real shared SQL search."""

from uuid import UUID, uuid4

import pytest

from linescope.application.reads import ReadTools
from linescope.domain.reference_normalization import close_codes
from linescope.execution import ExecutionContext


@pytest.mark.parametrize(
    "case",
    [
        "m204",
        "M204",
        "ｍ２０４",
        "M-204",
        "第1加工機",
        "第一加工機",
        "第１加工機",
        "boundary",
        "collision",
        "near",
    ],
)
def test_shared_demo_search_identity(db, case):
    db.migrate()
    with db.transaction() as c:
        for n, code, name in [
            (21, "M-204", "第1加工機"),
            (22, "M-208", "第2加工機"),
            (23, "M-211", "第11加工機"),
        ]:
            c.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES (%s,%s,%s,'machine',true)",
                (UUID(int=n), code, name),
            )
        if case == "collision":
            c.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES (%s,'M204','衝突装置','machine',true)",
                (UUID(int=24),),
            )
    reader, ctx = ReadTools(db), ExecutionContext("reader", "manager", uuid4())
    if case == "near":
        rows = reader.run(ctx, "search_equipment", {"filter": {}}).data["items"]
        assert [r["equipment_code"] for r in close_codes("M205", rows)] == ["M-204", "M-208"]
        return
    query = "第1" if case == "boundary" else "m204" if case == "collision" else case
    rows = reader.run(ctx, "search_equipment", {"filter": {"reference": query}}).data["items"]
    expected = (
        {str(UUID(int=21)), str(UUID(int=24))} if case == "collision" else {str(UUID(int=21))}
    )
    assert {r["equipment_id"] for r in rows} == expected
