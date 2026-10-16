from copy import deepcopy

import pytest
from application.test_proposals import context

from domain.test_economics import payload
from linescope.domain.canonical import canonical_hash, canonical_json
from linescope.domain.economics import calculate, economic_target, normalize_payload
from linescope.domain.snapshot import CanonicalSnapshot, build_economic_input_snapshot


def recovery_payload():
    p = payload()
    p.update(
        period_end="2026-10-31T00:00:00Z",
        operating_hours="480",
        cost_recovery={
            "daily_operating_hours": "16",
            "constant_daily_operation": True,
            "replacement_removes_degradation": True,
            "source": "承認対象の一定稼働・交換効果の試験仮定",
            "certainty": "ESTIMATED",
        },
    )
    for option in p["options"]:
        option["complete"] = True
        for row in option["items"]:
            row["valid_to"] = p["period_end"]
            if option["option"] == "REPLACE":
                row["amount"] = "2400000"
            if row["kind"] == "DEGRADATION":
                row.update(amount="1000", hours="480")
    return p


@pytest.mark.parametrize(
    "change",
    ["daily_limit", "bool_type", "source", "certainty", "unknown_field", "calendar_mismatch"],
)
def test_registered_assumption_boundaries_reject_invalid_values(change):
    p = recovery_payload()
    r = p["cost_recovery"]
    if change == "daily_limit":
        r["daily_operating_hours"] = "25"
    elif change == "bool_type":
        r["constant_daily_operation"] = "true"
    elif change == "source":
        r["source"] = ""
    elif change == "certainty":
        r["certainty"] = "UNKNOWN"
    elif change == "unknown_field":
        r["role"] = "manager"
    else:
        r["daily_operating_hours"] = "15"
    with pytest.raises(ValueError):
        normalize_payload(p)


@pytest.mark.parametrize(
    "condition,status,days",
    [
        ("KNOWN", "CONDITIONAL", "150"),
        ("MISSING", "UNKNOWN", None),
        ("NO_ELIMINATION", "UNKNOWN", None),
        ("ZERO_RATE", "NO_RECOVERY_FROM_DECLARED_LOSS", None),
        ("NONUNIFORM_DURATION", "UNKNOWN", None),
        ("ROUND_UP", "CONDITIONAL", "150.000001"),
    ],
)
def test_simple_recovery_keeps_assumptions_unknown_zero_and_rounding_distinct(
    condition, status, days
):
    p = recovery_payload()
    if condition == "MISSING":
        del p["cost_recovery"]
    elif condition == "NO_ELIMINATION":
        p["cost_recovery"]["replacement_removes_degradation"] = False
    elif condition == "NONUNIFORM_DURATION":
        p["options"][2]["items"][0]["hours"] = "16"
    elif condition == "ZERO_RATE":
        p["options"][2]["items"][0]["amount"] = "0"
    elif condition == "ROUND_UP":
        p["options"][1]["items"][0]["amount"] = "2400000.000001"
    result = calculate(p)
    r = result["simple_cost_recovery"]
    assert (r["status"], r["days"]) == (status, days)
    assert r["is_breakeven"] is False and r["recommendation"] is None
    if condition == "KNOWN":
        assert (
            next(row for row in result["options"] if row["option"] == "CONTINUE")["total_jpy"]
            == "480000"
        )
        assert r["inputs"]["degradation_loss_per_hour_jpy"] == "1000"


@pytest.mark.parametrize("mode", ["LEGACY", "DOWNGRADE"])
def test_snapshot_versions_preserve_old_bytes_and_reject_assumption_downgrade(mode):
    p = payload() if mode == "LEGACY" else recovery_payload()
    target = economic_target(
        {
            "input_code": "RECOVERY",
            "equipment_id": "20400000-0000-4000-8000-000000000001",
            "payload": p,
        }
    )
    snapshot = build_economic_input_snapshot(context(), [target])
    assert snapshot.data["schema_version"] == (2 if mode == "LEGACY" else 6)
    if mode == "LEGACY":
        original = {
            "schema_version": 2,
            "requester_id": context().authenticated_user_id,
            "supersedes_update_request_id": None,
            "targets": [target],
        }
        assert snapshot.canonical_text == canonical_json(original)
        assert snapshot.snapshot_hash == canonical_hash(original)
    elif mode == "DOWNGRADE":
        changed = snapshot.data
        changed["schema_version"] = 2
        with pytest.raises(ValueError):
            CanonicalSnapshot(canonical_json(changed), canonical_hash(changed))
    else:
        assert (
            CanonicalSnapshot(snapshot.canonical_text, snapshot.snapshot_hash).data == snapshot.data
        )


def test_absent_and_explicit_unknown_assumptions_are_not_silently_rewritten():
    p = payload()
    original = normalize_payload(p)
    assert "cost_recovery" not in original
    explicit = normalize_payload({**deepcopy(p), "cost_recovery": None})
    assert explicit["cost_recovery"] is None and canonical_hash(explicit) != canonical_hash(
        original
    )
    assert calculate(explicit)["simple_cost_recovery"]["days"] is None
