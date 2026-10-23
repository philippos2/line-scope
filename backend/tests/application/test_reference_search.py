"""Shared lexical lookup: equivalence classes, near misses and collision boundaries."""

from uuid import UUID

import pytest

from application.test_reads import context
from linescope.application.reads import ReadTools, ToolError


@pytest.mark.parametrize(
    "reference,code,name,other_code,other_name",
    [
        ("  ａＢ－０２  ", "Ab-02", "制御盤", "AB-2", "別設備"),
        ("ｶﾞｲﾄﾞe\u0301STRASSE", "R-3", "ガイドÉStraße装置", "R-4", "ガイドEStraße装置"),
        (
            "第二ラインの第１２制御盤",
            "R-5",
            "第2ラインの第十二制御盤",
            "R-6",
            "第2ラインの第十三制御盤",
        ),
        ("第1", "R-7", "第一制御盤", "R-8", "第十一制御盤"),
        ("A_%[x]", "R-9", "A_%[x]制御盤", "R-10", "Axxx制御盤"),
    ],
)
def test_shared_reference_preserves_equivalence_and_near_misses(
    db, reference, code, name, other_code, other_name
):
    db.migrate()
    with db.transaction() as connection:
        for number, candidate_code, candidate_name in (
            (1, code, name),
            (2, other_code, other_name),
        ):
            connection.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) "
                "VALUES(%s,%s,%s,'machine',true)",
                (UUID(int=number), candidate_code, candidate_name),
            )
    result = ReadTools(db).run(context(), "search_equipment", {"filter": {"reference": reference}})
    assert [row["equipment_id"] for row in result.data["items"]] == [str(UUID(int=1))]
    assert result.data["items"][0]["equipment_code"] == code
    assert result.data["items"][0]["equipment_name"] == name
    assert result.data["next_cursor"] is None
    assert result.evidence["source"] == "POSTGRESQL"


def test_reference_collisions_keep_real_ids_and_cursor_binding(db):
    db.migrate()
    with db.transaction() as connection:
        for number, code in ((1, "Rack-07"), (2, "ＲＡＣＫ－０７")):
            connection.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) "
                "VALUES(%s,%s,'制御盤','machine',true)",
                (UUID(int=number), code),
            )
    tools = ReadTools(db)
    arguments = {"filter": {"reference": "rack-07"}, "page_size": 1}
    first = tools.run(context(), "search_equipment", arguments)
    assert [row["equipment_id"] for row in first.data["items"]] == [str(UUID(int=1))]
    assert first.data["next_cursor"]
    second = tools.run(
        context(), "search_equipment", {**arguments, "cursor": first.data["next_cursor"]}
    )
    assert [row["equipment_id"] for row in second.data["items"]] == [str(UUID(int=2))]
    assert second.data["next_cursor"] is None
    with pytest.raises(ToolError) as error:
        tools.run(
            context(),
            "search_equipment",
            {"filter": {"reference": "another"}, "cursor": first.data["next_cursor"]},
        )
    assert error.value.code == "INVALID_ARGUMENT"
    # Existing opaque-code lookup remains strict and still supports AND filters.
    strict = tools.run(context(), "search_equipment", {"filter": {"equipment_code": "Rack-07"}})
    assert len(strict.data["items"]) == 1
    combined = tools.run(
        context(),
        "search_equipment",
        {"filter": {"reference": "rack-07", "equipment_code": "ＲＡＣＫ－０７"}},
    )
    assert [row["equipment_id"] for row in combined.data["items"]] == [str(UUID(int=2))]
