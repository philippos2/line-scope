from copy import deepcopy

import pytest
from incident_loss_fixture import END, START, records

from linescope.demo_graph_seed import demo_id
from linescope.domain.incident_loss import aggregate, normalize_losses


def world():
    inputs = [
        target["after"] for queries, target in records() if queries.INPUT.name == "economic_input"
    ]
    impacts = [
        {
            "equipment_id": row["equipment_id"],
            "state_code": "STOPPED",
            "complete": True,
            "product_ids": [item["product_id"] for item in row["payload"]["incident_losses"]],
        }
        for row in inputs
    ]
    return impacts, inputs


def test_same_global_product_scope_counts_once_across_equipment():
    impacts, inputs = world()
    result = aggregate(impacts, inputs, (START, END))
    assert result["complete"] and result["loss_per_hour"] == "250000"
    shared = next(row for row in result["items"] if row["product_id"] == str(demo_id("P-100")))
    assert shared["counted_times"] == 1 and len(shared["assertions"]) == 2
    assert not result["actual_damage_confirmed"] and result["cumulative_loss"] is None


@pytest.mark.parametrize("change", ["unknown", "nonindependent", "conflict", "period", "missing"])
def test_incomplete_or_conflicting_scopes_never_produce_complete_total(change):
    impacts, inputs = world()
    item = inputs[0]["payload"]["incident_losses"][0]
    if change == "unknown":
        item["loss_per_hour"] = None
    elif change == "nonindependent":
        item["independent"] = False
    elif change == "conflict":
        item["loss_per_hour"] = "999999"
    elif change == "period":
        inputs[0]["payload"]["period_start"] = "2026-10-17T00:00:00Z"
    else:
        inputs.pop()
    result = aggregate(impacts, inputs, (START, END))
    assert result["loss_per_hour"] is None and result["missing_information"]
    assert result["known_subtotal_per_hour"] is not None
    if change in {"unknown", "nonindependent", "conflict"}:
        assert result["known_subtotal_per_hour"] == "130000"


def test_loss_normalization_rejects_untyped_product_and_duplicate_scope():
    _, inputs = world()
    values = deepcopy(inputs[0]["payload"]["incident_losses"])
    values[0]["product_id"] = "P-100"
    with pytest.raises(ValueError):
        normalize_losses(values)
    with pytest.raises(ValueError):
        normalize_losses([values[1], values[1]])


def test_incident_snapshot_v7_cannot_downgrade_and_legacy_remains_v2():
    from uuid import uuid4

    from linescope.domain.canonical import canonical_hash, canonical_json
    from linescope.domain.economics import economic_target
    from linescope.domain.snapshot import CanonicalSnapshot, build_economic_input_snapshot
    from linescope.execution import ExecutionContext

    _, inputs = world()
    record = inputs[0]
    value = {key: record[key] for key in ("input_code", "equipment_id", "payload")}
    context = ExecutionContext("requester", "manager", uuid4())
    snapshot = build_economic_input_snapshot(context, [economic_target(value)])
    assert snapshot.data["schema_version"] == 7
    changed = snapshot.data
    changed["schema_version"] = 2
    with pytest.raises(ValueError):
        CanonicalSnapshot(canonical_json(changed), canonical_hash(changed))
    del value["payload"]["incident_losses"]
    assert (
        build_economic_input_snapshot(context, [economic_target(value)]).data["schema_version"] == 2
    )
