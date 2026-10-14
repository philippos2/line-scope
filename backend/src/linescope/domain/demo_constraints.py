"""Explain prototype option exclusions and unknowns; never grant execution authority."""


def assess_options(profile, *, current_state, state_evidence):
    inputs = profile["inputs"]
    if profile["source"] != "MOCK_FIXTURE":
        raise ValueError("Only explicit demo inputs are supported")
    for option in profile["options"]:
        name = option["option"]
        constraints, missing = [], []
        if name == "CONTINUE":
            if current_state in {"STOPPED", "UNDER_MAINTENANCE"}:
                constraints.append(
                    {
                        "code": "CURRENT_EQUIPMENT_UNAVAILABLE",
                        "source": "POSTGRESQL",
                        "state": current_state,
                        "evidence": state_evidence,
                    }
                )
            if inputs["hard_safety_stop"] is True:
                constraints.append(
                    {
                        "code": "HARD_SAFETY_STOP",
                        "source": "MOCK_FIXTURE",
                        "input_version": profile["fixture_version"],
                    }
                )
            if inputs["hard_safety_stop"] is not True:
                missing.append("approved_continued_operation_safety_conditions")
            missing.extend(["degradation_progression", "quality_and_delivery_impact"])
        elif name == "SUBSTITUTE":
            missing.extend(
                [
                    "substitute_compatibility",
                    "substitute_availability",
                    "approved_safety_conditions",
                ]
            )
            if option["shortage_units_per_hour"] is None:
                missing.append("required_and_available_capacity")
            elif option["shortage_units_per_hour"] > 0:
                constraints.append(
                    {
                        "code": "INSUFFICIENT_CAPACITY_FOR_FULL_ABSORPTION",
                        "source": "MOCK_FIXTURE",
                        "scope": "FULL_ABSORPTION",
                        "shortage": option["shortage_units_per_hour"],
                    }
                )
            # Insufficient full absorption does not rule out a partial mitigation.
        elif name == "REPAIR":
            for key in ("repair_cost", "repair_hours"):
                if inputs[key] is None:
                    missing.append(key)
            if option["production_loss"] is None:
                missing.append("complete_loss_rate")
            missing.extend(["repair_resources_and_availability", "post_repair_risk"])
        elif name == "REPLACE":
            missing.extend(
                ["replacement_work_duration", "interim_operation_plan", "replacement_downtime_loss"]
            )
            for key in ("replacement_cost", "replacement_lead_days"):
                if inputs[key] is None:
                    missing.append(key)
        option["blocking_constraints"] = constraints
        option["missing_information"] = sorted(set(missing))
        option["residual_risk"] = "UNKNOWN"
        # A fixture's absence of a stop flag is not positive safety permission.
        option["feasibility"] = "INFEASIBLE" if name == "CONTINUE" and constraints else "UNKNOWN"
        option["assessment_complete"] = False
    profile["excluded_options"] = [
        item["option"] for item in profile["options"] if item["feasibility"] == "INFEASIBLE"
    ]
    profile["decision_completeness"] = "PARTIAL"
    profile["required_information"] = sorted(
        {key for option in profile["options"] for key in option["missing_information"]}
    )
    return profile
