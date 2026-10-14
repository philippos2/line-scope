from types import SimpleNamespace

import pytest

from linescope.application.decision_maintenance import maintenance_context
from linescope.application.reads import ToolError


class Reads:
    def __init__(self, *, plans=None, records=None, cursor=None, error=None):
        self.plans, self.records = plans or [], records or []
        self.cursor, self.error = cursor, error
        self.calls = []

    def run(self, context, tool, arguments):
        self.calls.append((context, tool, arguments))
        if self.error and tool == "search_maintenance_records":
            raise ToolError(self.error, "internal details must not be exposed")
        return SimpleNamespace(
            data={
                "items": self.plans if tool.endswith("plans") else self.records,
                "next_cursor": self.cursor,
            },
            evidence={"source": "POSTGRESQL", "tool": tool, "observed_at": "server-time"},
        )


def test_registered_empty_history_does_not_imply_no_failures():
    result = maintenance_context(Reads(), "trusted", "equipment")
    assert result["retrieval_complete"]
    assert result["records"]["status"] == "AVAILABLE"
    assert result["records"]["items"] == []
    assert not result["assessment_complete"]
    assert "future_failure_probability" in result["unknowns"]


def test_reads_keep_equipment_filter_context_and_bounded_calls():
    reads = Reads()
    maintenance_context(reads, "trusted", "equipment")
    assert len(reads.calls) == 2
    assert all(call[0] == "trusted" for call in reads.calls)
    assert all(
        call[2] == {"filter": {"equipment_id": "equipment"}, "page_size": 100}
        for call in reads.calls
    )


def test_retrieved_facts_are_ordered_without_next_plan_inference():
    reads = Reads(
        plans=[
            {"planned_start": "2026-11-02", "maintenance_plan_id": "b"},
            {"planned_start": "2026-11-01", "maintenance_plan_id": "a"},
        ],
        records=[
            {"performed_at": "2026-10-01", "maintenance_record_id": "a", "result": "修理"},
            {"performed_at": "2026-10-02", "maintenance_record_id": "b", "result": "点検"},
        ],
    )
    result = maintenance_context(reads, "trusted", "equipment")
    assert result["plans"]["items"][0]["maintenance_plan_id"] == "a"
    assert result["records"]["items"][0]["result"] == "点検"
    assert "next_plan" not in result
    assert "failure_and_repair_classification" in result["unknowns"]


def test_limit_keeps_partial_facts_and_evidence():
    result = maintenance_context(Reads(cursor="opaque"), "trusted", "equipment")
    assert result["plans"]["status"] == "TRUNCATED"
    assert not result["retrieval_complete"]
    assert result["plans"]["evidence"]["tool"] == "search_maintenance_plans"


def test_dependency_failure_keeps_other_facts_without_raw_error():
    result = maintenance_context(Reads(error="DEPENDENCY_UNAVAILABLE"), "trusted", "equipment")
    assert result["plans"]["status"] == "AVAILABLE"
    assert result["records"]["status"] == "UNAVAILABLE"
    assert result["records"]["evidence"] is None
    assert result["records"]["error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert "internal details" not in str(result)
    assert not result["retrieval_complete"]


def test_authorization_failure_rejects_package():
    with pytest.raises(ToolError) as error:
        maintenance_context(Reads(error="AUTHORIZATION_DENIED"), "trusted", "equipment")
    assert error.value.code == "AUTHORIZATION_DENIED"
