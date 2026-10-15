from copy import deepcopy

import pytest

from linescope.domain.economics import calculate, normalize_payload

START = "2026-10-01T00:00:00Z"
END = "2026-10-02T00:00:00Z"


def item(key="repair", kind="DIRECT", amount="300000", hours=None):
    return {
        "key": key,
        "kind": kind,
        "amount": amount,
        "hours": hours,
        "independent": True,
        "source": "保全見積書 '); DROP TABLE equipment; --",
        "certainty": "ESTIMATED",
        "valid_from": START,
        "valid_to": END,
    }


def payload():
    return {
        "period_start": START,
        "period_end": END,
        "operating_hours": "16.000000",
        "currency": "JPY",
        "options": [
            {
                "option": "REPAIR",
                "complete": True,
                "items": [
                    item(),
                    item("P100", "STOPPAGE", "120000", "8"),
                    item("P200", "STOPPAGE", "80000", "8"),
                ],
            },
            {
                "option": "REPLACE",
                "complete": False,
                "items": [item("replacement", amount="3000000")],
            },
            {
                "option": "CONTINUE",
                "complete": True,
                "items": [item("degradation", "DEGRADATION", "1000.125", "16")],
            },
        ],
    }


def test_exact_registered_calculation_separates_subtotal_unknown_and_feasibility():
    result = calculate(payload())
    options = {row["option"]: row for row in result["options"]}
    assert options["REPAIR"]["total_jpy"] == "1900000"
    assert options["CONTINUE"]["total_jpy"] == "16002.000"
    assert options["REPLACE"]["known_subtotal_jpy"] == "3000000"
    assert options["REPLACE"]["total_jpy"] is None
    assert result["feasibility"] == "UNKNOWN" and result["recommendation"] is None


def test_normalization_preserves_sources_and_canonicalizes_decimal_time_and_sets():
    values = payload()
    expected = normalize_payload(values)
    values["options"].reverse()
    values["options"][2]["items"].reverse()
    values["period_start"] = "2026-10-01T09:00:00+09:00"
    assert normalize_payload(values) == expected
    assert expected["operating_hours"] == "16"
    assert "DROP TABLE" in expected["options"][1]["items"][2]["source"]


@pytest.mark.parametrize("change", ["unknown_rate", "unknown_hours", "nonindependent"])
def test_unknown_or_nonindependent_loss_never_becomes_zero(change):
    values = payload()
    loss = values["options"][0]["items"][1]
    if change == "unknown_rate":
        loss["amount"] = None
    elif change == "unknown_hours":
        loss["hours"] = None
    else:
        loss["independent"] = False
    repair = next(row for row in calculate(values)["options"] if row["option"] == "REPAIR")
    assert repair["total_jpy"] is None
    assert repair["known_subtotal_jpy"] == "940000"
    assert repair["unknown_or_nonindependent_keys"] == ["P100"]


@pytest.mark.parametrize("change", ["float", "period", "overlap"])
def test_invalid_decimal_period_or_duplicate_scope_is_rejected(change):
    values = deepcopy(payload())
    if change == "float":
        values["options"][0]["items"][0]["amount"] = 0.1
    elif change == "period":
        values["options"][0]["items"][0]["valid_to"] = "2026-10-01T12:00:00Z"
    else:
        values["options"][0]["items"].append(deepcopy(values["options"][0]["items"][0]))
    with pytest.raises(ValueError):
        normalize_payload(values)
