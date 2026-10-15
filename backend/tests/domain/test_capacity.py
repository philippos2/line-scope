import pytest

from linescope.domain.capacity import calculate, normalize_payload


def payload():
    return {
        "period_start": "2026-10-01T00:00:00Z",
        "period_end": "2026-10-02T00:00:00Z",
        "quantity_unit": "units",
        "required_rate": "90",
        "normal_rate": "100",
        "used_rate": "20",
        "reserved_rate": "20",
        "loads_independent": True,
        "loads_complete": True,
        "compatible": True,
        "source": "生産計画 '); DROP TABLE equipment; --",
        "certainty": "CONFIRMED",
        "recovery": {
            "buffer": "120",
            "stopped_at": "2026-10-01T00:00:00Z",
            "constant_flow": True,
            "no_other_allocations": True,
            "recovery_meets_demand": True,
        },
    }


@pytest.mark.parametrize(
    "required,normal,available,status,shortage",
    [
        ("60", "120", "80", "SUFFICIENT", "0"),
        ("90", "100", "60", "INSUFFICIENT", "30"),
        ("0", "40", "0", "SUFFICIENT", "0"),
    ],
)
def test_same_product_rate_comparison_preserves_zero_and_shortage(
    required, normal, available, status, shortage
):
    values = payload()
    values["required_rate"] = required
    values["normal_rate"] = normal
    result = calculate(values)
    assert result["available_rate"] == available
    assert result["capacity_status"] == status and result["shortage_rate"] == shortage
    assert result["feasibility"] == "UNKNOWN"


def test_missing_reserved_load_does_not_become_spare_capacity():
    values = payload()
    values["reserved_rate"] = None
    result = calculate(values)
    assert result["available_rate"] is result["shortage_rate"] is None
    assert (
        result["capacity_status"] == "UNKNOWN" and "reserved_rate" in result["missing_information"]
    )


def test_invalid_period_is_rejected_before_calculation():
    values = payload()
    values["period_end"] = values["period_start"]
    with pytest.raises(ValueError):
        normalize_payload(values)


def test_incompatible_product_does_not_gain_feasibility_or_recovery_deadline():
    values = payload()
    values["compatible"] = False
    result = calculate(values)
    assert result["capacity_status"] == "INCOMPATIBLE"
    assert result["recovery_deadline"] is None and result["feasibility"] == "UNKNOWN"


def test_constant_flow_buffer_returns_conditional_four_hour_deadline():
    result = calculate(payload())
    assert result["recovery_status"] == "CONDITIONAL"
    assert result["permissible_downtime_hours"] == "4"
    assert result["recovery_deadline"] == "2026-10-01T04:00:00.000000Z"
    assert result["recovery_assumptions"]["buffer"] == "120"


def test_unconfirmed_allocation_assumption_does_not_produce_deadline():
    values = payload()
    values["recovery"]["no_other_allocations"] = False
    result = calculate(values)
    assert result["capacity_status"] == "INSUFFICIENT"
    assert result["recovery_status"] == "UNKNOWN" and result["recovery_deadline"] is None
