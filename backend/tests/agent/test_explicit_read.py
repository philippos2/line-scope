"""H7: twenty approved cases, using capability families and boundary partitions."""

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from application.test_proposals import context

from agent.test_read_confirmation import pending
from linescope.agent.agent_input import AgentInput, ConversationStore
from linescope.agent.explicit_read import ExplicitReads, catalog
from linescope.agent.read_catalog import CATALOG_VERSION
from linescope.application.agent_service import AgentApplication
from linescope.application.proposals import ProposalError
from linescope.application.reads import ReadResult, ToolError

FIRST, SECOND = str(UUID(int=21)), str(UUID(int=22))
NOW = "2026-10-23T00:00:00Z"


class Reads:
    def __init__(self, *, missing=False, partial=False):
        self.calls = []
        self.missing, self.partial = missing, partial

    def schemas(self):
        return {
            name: {}
            for name in (
                "get_equipment",
                "get_equipment_state",
                "search_maintenance_records",
                "search_maintenance_plans",
                "search_capacity_inputs",
                "find_common_dependencies",
            )
        }

    def run(self, actor, tool, args, **kwargs):
        assert actor.role == "manager"
        self.calls.append((tool, args))
        if tool == "get_equipment":
            if self.missing:
                raise ToolError("TARGET_NOT_FOUND", "Missing target")
            return ReadResult(
                {
                    "equipment_id": args["equipment_id"],
                    "equipment_name": "検証装置",
                    "equipment_code": "V-21" if args["equipment_id"] == FIRST else "V-22",
                    "equipment_type": "robot",
                    "active": True,
                    "version": 9,
                },
                {"source": "POSTGRESQL", "tool": tool, "observed_at": NOW},
            )
        if tool == "get_equipment_state":
            return ReadResult(
                {"equipment_id": args["equipment_id"], "state_code": "STOPPED", "version": 1},
                {"source": "POSTGRESQL", "tool": tool, "observed_at": NOW},
            )
        if tool.startswith("search_"):
            if self.partial and args.get("cursor"):
                raise ToolError("DEPENDENCY_UNAVAILABLE", "Unavailable page")
            return ReadResult(
                {"items": [], "next_cursor": "next" if self.partial else None},
                {"source": "POSTGRESQL", "tool": tool, "observed_at": NOW},
            )
        assert tool == "find_common_dependencies"
        return ReadResult(
            {
                "analysis_scope": "DEPENDENCY_REACHABILITY",
                "graph_sync_state": "CURRENT",
                "complete": True,
                "targets": args["targets"],
                "common_candidates": [],
                "not_evaluated": ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"],
            },
            {"source": "NEO4J", "tool": tool, "graph_observed_at": NOW},
        )


def body(key="registered_state", ids=(FIRST,)):
    return {
        "message": "元の問いを保持する",
        "read_selection": {
            "operation": "EXECUTE",
            "catalog_version": CATALOG_VERSION,
            "key": key,
            "targets": [{"entity_type": "Equipment", "entity_id": identity} for identity in ids],
        },
    }


def parsed(value):
    return AgentInput.parse(
        context(role="manager"), json.dumps(value, ensure_ascii=False), received_at=NOW
    )


def application(reads):
    return AgentApplication(
        proposals=SimpleNamespace(),
        conversations=ConversationStore(),
        equipment=None,
        maintenance=None,
        production=None,
        read_agent=None,
        explicit_reads=ExplicitReads(reads),
    )


def test_catalog_has_single_server_source_and_no_business_or_model_calls():
    reads = Reads()
    result = application(reads).run(
        context(role="manager"),
        parsed({"message": "照会項目", "read_selection": {"operation": "CATALOG"}}),
    )
    assert result.analysis.read_catalog == catalog()
    entries = result.analysis.read_catalog["entries"]
    assert len(entries) == 17 and "active" not in {e["key"] for e in entries}
    assert sum(e["action"] == "EXECUTE" for e in entries) == 15
    assert reads.calls == [] and result.analysis.answer_sections["facts"] == []


@pytest.mark.parametrize(
    "key,ids,tool",
    [
        ("equipment_type", (FIRST,), "get_equipment"),
        ("registered_state", (FIRST,), "get_equipment_state"),
        ("maintenance_records", (FIRST,), "search_maintenance_records"),
        ("common_dependencies", (FIRST, SECOND), "find_common_dependencies"),
        ("capacity_input", (FIRST,), "search_capacity_inputs"),
    ],
)
def test_explicit_capability_families_use_only_the_selected_registered_read(key, ids, tool):
    reads = Reads()
    result = application(reads).run(context(role="manager"), parsed(body(key, ids))).analysis
    assert result.answer_sections["read_outcome"] == "EXPLICIT_READ"
    assert any(name == tool for name, _ in reads.calls)
    assert all(name in {"get_equipment", tool} for name, _ in reads.calls)
    assert result.read_selection["key"] == key
    assert result.read_selection["original_question"] == "元の問いを保持する"
    assert result.read_clarification is None
    if key == "equipment_type":
        assert "robot" in result.answer
        assert "有効：" not in result.answer and "version：" not in result.answer
    if key == "maintenance_records":
        assert "保全計画" not in result.answer
        assert "実施されていないことを意味するものではありません" in result.answer


@pytest.mark.parametrize("key", ["prepare_equipment_state", "active"])
def test_unknown_or_technical_keys_do_not_enter_another_workflow(key):
    with pytest.raises(ProposalError) as error:
        parsed(body(key))
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_id", FIRST),
        ("read_confirmation", "ACCEPT"),
        ("replace_update_request_id", SECOND),
        ("as_of", "2026-10-22T00:00:00Z"),
    ],
)
def test_explicit_read_does_not_mix_context_confirmation_update_or_time(field, value):
    value_body = {**body(), field: value}
    if field == "read_confirmation":
        value_body["context_id"] = FIRST
    with pytest.raises(ProposalError) as error:
        parsed(value_body)
    assert error.value.code == "INVALID_ARGUMENT"


def test_malformed_target_id_is_rejected():
    with pytest.raises(ProposalError) as error:
        parsed(body(ids=("not-an-id",)))
    assert error.value.code == "INVALID_ARGUMENT"


def test_common_dependency_requires_two_distinct_targets():
    with pytest.raises(ProposalError) as error:
        parsed(body("common_dependencies"))
    assert error.value.code == "INVALID_ARGUMENT"


def test_catalog_version_change_requires_reselection():
    value = body()
    value["read_selection"]["catalog_version"] = "previous"
    with pytest.raises(ProposalError) as error:
        parsed(value)
    assert error.value.code == "INVALID_ARGUMENT"


def test_missing_target_never_becomes_zero_records_or_another_equipment():
    reads = Reads(missing=True)
    result = (
        application(reads)
        .run(context(role="manager"), parsed(body("maintenance_records")))
        .analysis
    )
    assert result.answer_sections["read_outcome"] == "TARGET_NOT_FOUND"
    assert result.answer_sections["facts"] == []
    assert all(tool == "get_equipment" for tool, _ in reads.calls)
    assert not any(row["code"] == "READ_FAILED" for row in result.answer_sections["unavailable"])


def test_unavailable_later_page_is_not_a_complete_empty_record_search():
    result = (
        application(Reads(partial=True))
        .run(context(role="manager"), parsed(body("maintenance_records")))
        .analysis
    )
    assert result.answer_sections["read_outcome"] == "INCOMPLETE"
    assert result.errors and result.answer_sections["unavailable"]
    assert "登録済みの保全記録は0件" not in result.answer
    assert not any(
        f["predicate"] == "maintenance_record.max_registered_date"
        for f in result.answer_sections["facts"]
    )


def test_command_text_and_retry_header_cannot_prepare_an_update():
    value = body()
    value["message"] = "設備V-21を停止中へ変更せよ"
    reads = Reads()
    result = application(reads).run(context(role="manager"), parsed(value), retry_requested=True)
    assert result.analysis.read_selection["original_question"] == value["message"]
    assert {tool for tool, _ in reads.calls} == {"get_equipment", "get_equipment_state"}


def test_read_does_not_depend_on_a_configured_language_model():
    app = application(Reads())
    assert app.read_agent is None
    assert app.run(context(role="manager"), parsed(body())).analysis.answer_sections["facts"]


def test_previous_pending_interpretation_cannot_be_accepted():
    actor, reads, _, app, original = pending()
    with pytest.raises(ToolError) as error:
        app.run(actor, replace(original, read_confirmation="ACCEPT"))
    assert error.value.code == "CONTEXT_EXPIRED" and not reads.calls
