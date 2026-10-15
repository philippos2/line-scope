import pytest

from linescope.domain.safety import calculate, normalize_payload

AT = "2026-10-16T00:00:00Z"


def payload():
    return {
        "period_start": "2020-01-01T00:00:00Z",
        "period_end": "2099-01-01T00:00:00Z",
        "observation": "精度劣化を点検で確認",
        "criterion": "承認済み点検基準S-1",
        "source": "点検記録 '); DROP TABLE equipment; --",
        "conditions": "点検条件を遵守し次回点検まで監視",
        "decision": "STOP_REQUIRED",
        "certainty": "CONFIRMED",
        "risk_notes": None,
    }


@pytest.mark.parametrize(
    "decision,candidate",
    [("STOP_REQUIRED", "EXCLUDED"), ("CONDITIONAL", "CONDITIONAL"), ("UNKNOWN", "UNASSESSED")],
)
def test_registered_declaration_keeps_stop_conditional_and_unknown_separate(decision, candidate):
    value = payload()
    value["decision"] = decision
    result = calculate(value, AT)
    assert result["status"] == decision and result["continue_candidate"] == candidate
    assert result["operational_permission"] is False and result["residual_risk"] == "UNKNOWN"


def test_expired_declaration_does_not_authorize_continuation():
    value = payload()
    value["decision"] = "CONDITIONAL"
    value["period_end"] = AT
    result = calculate(value, AT)
    assert result["status"] == "UNKNOWN" and "outside_valid_period" in result["missing_information"]


def test_missing_conditions_do_not_become_safety_permission():
    value = payload()
    value["decision"] = "CONDITIONAL"
    value["conditions"] = None
    assert calculate(value, AT)["continue_candidate"] == "UNASSESSED"


def test_invalid_validity_period_is_rejected():
    value = payload()
    value["period_end"] = value["period_start"]
    with pytest.raises(ValueError):
        normalize_payload(value)


def test_estimated_basis_does_not_confirm_continuation():
    value = payload()
    value["decision"] = "CONDITIONAL"
    value["certainty"] = "ESTIMATED"
    assert calculate(value, AT)["status"] == "UNKNOWN"


def test_future_declaration_is_not_current_permission():
    value = payload()
    value["period_start"] = "2030-01-01T00:00:00Z"
    assert calculate(value, AT)["status"] == "UNKNOWN"
