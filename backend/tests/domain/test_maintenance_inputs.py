import pytest

from linescope.domain.maintenance_inputs import calculate, normalize_payload

AT = "2026-10-16T00:00:00Z"


def payload():
    return {
        "kind": "REPLACEMENT_PLAN",
        "period_start": "2020-01-01T00:00:00Z",
        "period_end": "2099-01-01T00:00:00Z",
        "source": "見積書 '); DROP TABLE equipment; --",
        "details": "部品到着まで14日、交換の作業と停止は別記",
        "risk_notes": None,
        "maintenance_plan_id": None,
        "lead_time_hours": "336",
        "work_hours": "4",
        "downtime_hours": "2",
        "direct_cost_jpy": "10000",
        "replacement_cost_jpy": "20000",
        "include_replacement_cost": True,
        "past_loss_jpy": None,
        "interim_until": None,
    }


@pytest.mark.parametrize("kind", ["REPAIR_PLAN", "REPLACEMENT_PLAN", "INTERIM_PLAN"])
def test_plan_keeps_lead_work_stop_and_explicit_cost_period_separate(kind):
    p = payload()
    p["kind"] = kind
    if kind == "INTERIM_PLAN":
        p["interim_until"] = "2030-01-15T00:00:00Z"
    c = calculate(p, AT)
    assert (c["lead_time_hours"], c["work_hours"], c["downtime_hours"]) == ("336", "4", "2")
    assert c["known_plan_direct_cost_subtotal_jpy"] == "30000"
    assert c["total_economic_impact_jpy"] is None and c["automatic_state_change"] is False
    assert c["period_end"].startswith("2099-") and c["feasibility"] == "UNASSESSED"


@pytest.mark.parametrize("kind", ["FAILURE_RECORD", "REPAIR_RECORD"])
def test_historical_loss_remains_fact_without_future_probability(kind):
    p = payload()
    p.update(
        kind=kind,
        period_end="2021-01-01T00:00:00Z",
        lead_time_hours=None,
        replacement_cost_jpy=None,
        include_replacement_cost=None,
        past_loss_jpy="120000",
    )
    c = calculate(p, AT)
    assert c["past_loss_jpy"] == "120000" and c["record_scope"] == "HISTORICAL"
    assert c["future_failure_probability"] is None
    assert c["known_plan_direct_cost_subtotal_jpy"] is None


def test_unknown_cost_inclusion_is_not_zero_or_a_total():
    p = payload()
    p.update(include_replacement_cost=None, downtime_hours=None)
    c = calculate(p, AT)
    assert c["known_plan_direct_cost_subtotal_jpy"] is None
    assert "include_replacement_cost" in c["missing_information"]
    assert "downtime_hours" in c["missing_information"]


def test_nonincreasing_period_rejected():
    p = payload()
    p["period_end"] = p["period_start"]
    with pytest.raises(ValueError):
        normalize_payload(p)


def test_historical_record_cannot_smuggle_future_plan_values():
    p = payload()
    p["kind"] = "FAILURE_RECORD"
    with pytest.raises(ValueError):
        normalize_payload(p)
