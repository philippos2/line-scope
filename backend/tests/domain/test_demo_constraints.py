from linescope.domain.demo_comparison import compare, fixture
from linescope.domain.demo_constraints import assess_options


def assess(state="RUNNING", **changes):
    inputs = fixture("DEGRADED")
    inputs.update(changes)
    return assess_options(compare(inputs), current_state=state, state_evidence={"version": 4})


def test_economic_advantage_cannot_override_mock_safety_stop():
    result = assess(hard_safety_stop=True)
    continuation = result["options"][3]
    assert continuation["cumulative_degradation_loss"] == 480000
    assert continuation["feasibility"] == "INFEASIBLE"
    assert continuation["blocking_constraints"][0]["code"] == "HARD_SAFETY_STOP"
    assert continuation["blocking_constraints"][0]["source"] == "MOCK_FIXTURE"
    assert result["excluded_options"] == ["CONTINUE"]


def test_current_state_and_mock_constraint_keep_separate_evidence():
    result = assess("STOPPED", hard_safety_stop=True)
    constraints = result["options"][3]["blocking_constraints"]
    assert [item["source"] for item in constraints] == ["POSTGRESQL", "MOCK_FIXTURE"]
    assert constraints[0]["evidence"] == {"version": 4}


def test_unknown_safety_never_becomes_permission():
    result = assess()
    option = result["options"][3]
    assert option["feasibility"] == "UNKNOWN"
    assert "approved_continued_operation_safety_conditions" in option["missing_information"]
    assert result["decision_completeness"] == "PARTIAL"


def test_no_mock_stop_is_not_approved_safe_operation():
    result = assess(hard_safety_stop=False)
    assert result["options"][3]["feasibility"] == "UNKNOWN"
    assert result["options"][3]["residual_risk"] == "UNKNOWN"
    assert (
        "approved_continued_operation_safety_conditions"
        in result["options"][3]["missing_information"]
    )


def test_partial_substitution_is_not_wholly_ruled_out_by_capacity():
    result = assess_options(compare(fixture("STOPPED")), current_state="STOPPED", state_evidence={})
    option = result["options"][2]
    assert option["shortage_units_per_hour"] == 30
    assert option["feasibility"] == "UNKNOWN"
    assert option["blocking_constraints"][0]["code"] == "INSUFFICIENT_CAPACITY_FOR_FULL_ABSORPTION"
    assert result["economic_preference"] is None


def test_incomplete_cost_information_is_enumerated():
    result = assess()
    assert "repair_cost" in result["options"][0]["missing_information"]
    assert "replacement_downtime_loss" in result["required_information"]
    assert all(option["assessment_complete"] is False for option in result["options"])
