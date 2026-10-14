"""Authorized, bounded maintenance facts for a current decision package.

Each search observes its own PostgreSQL snapshot. No failure classification,
next-plan selection, cost or future risk is inferred from these records.
"""

from .reads import ToolError


def maintenance_context(reads, context, equipment_id):
    sections = {}
    for name, tool in (
        ("plans", "search_maintenance_plans"),
        ("records", "search_maintenance_records"),
    ):
        try:
            result = reads.run(
                context, tool, {"filter": {"equipment_id": equipment_id}, "page_size": 100}
            )
        except ToolError as error:
            if error.code not in {"DEPENDENCY_UNAVAILABLE", "RESOURCE_BUSY"}:
                raise
            sections[name] = {
                "status": "UNAVAILABLE",
                "items": [],
                "complete": False,
                "error_code": error.code,
                "evidence": None,
            }
            continue
        complete = result.data["next_cursor"] is None
        sections[name] = {
            "status": "AVAILABLE" if complete else "TRUNCATED",
            "items": result.data["items"],
            "complete": complete,
            "evidence": result.evidence,
        }
    # Order only retrieved facts; never label the earliest plan as the next plan.
    sections["plans"]["items"] = sorted(
        sections["plans"]["items"],
        key=lambda row: (row["planned_start"], row["maintenance_plan_id"]),
    )
    sections["records"]["items"] = sorted(
        sections["records"]["items"],
        key=lambda row: (row["performed_at"], row["maintenance_record_id"]),
        reverse=True,
    )
    return {
        "source": "POSTGRESQL",
        "consistency": "LATEST_PER_CALL",
        "scope": "CURRENT_REGISTERED_MAINTENANCE",
        "equipment_id": equipment_id,
        **sections,
        "retrieval_complete": all(section["complete"] for section in sections.values()),
        "assessment_complete": False,
        "unknowns": [
            "failure_and_repair_classification",
            "historical_downtime_and_loss",
            "future_failure_probability",
            "next_plan_selection_rule",
            "repair_and_replacement_plan_classification",
        ],
    }
