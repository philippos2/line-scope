"""H6-R: five server cases; U19 validates the browser evaluator separately."""

import io
from uuid import UUID

import pytest
from application.test_proposals import context
from fastapi.testclient import TestClient

from agent.test_read_agent import request
from linescope.agent.read_agent import ReadAgent
from linescope.agent.read_scope import PLAN_TOOL
from linescope.agent.scope_check import CHECK_TOOL
from linescope.application.reads import ReadResult
from linescope.application.tools import ToolDispatcher
from linescope.integrations.llm import LLMReply, ToolCall
from linescope.interfaces.api import create_app
from linescope.logging import EventLogger
from linescope.settings import Settings


@pytest.fixture
def equipment(db):
    db.migrate()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) "
            "VALUES(%s,'E-7','搬送装置','machine',true)",
            (UUID(int=7),),
        )
    return db


class ObservedReads:
    def __init__(self, db):
        self.delegate = ToolDispatcher(db)
        self.calls = []

    def schemas(self):
        return {
            **self.delegate.schemas(),
            **{
                tool: {}
                for tool in (
                    "trace_downstream_impact",
                    "find_alternative_paths",
                    "find_single_point_failure_candidates",
                )
            },
        }

    def run(self, context, tool, arguments, **kwargs):
        self.calls.append((tool, arguments))
        if tool == "trace_downstream_impact":
            return ReadResult(
                {
                    "analysis_scope": "DEPENDENCY_REACHABILITY",
                    "graph_sync_state": "CURRENT",
                    "complete": True,
                    "reached_nodes": [],
                    "direct_nodes": [],
                    "indirect_nodes": [],
                    "not_evaluated": ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"],
                },
                {"source": "CONTROLLED_GRAPH_RESULT"},
            )
        return self.delegate.run(context, tool, arguments, **kwargs)


class Plan:
    def __init__(self, *, malformed=False):
        self.malformed = malformed
        self.calls = []

    def complete(self, messages, *, schemas, deadline):
        self.calls.append(tuple(schemas))
        if self.malformed:
            return LLMReply("No structured plan", ())
        if CHECK_TOOL in schemas:
            # A malformed coverage result must block values, not erase identity.
            return LLMReply(
                "", (ToolCall("check", CHECK_TOOL, {"verdict": "MATCH", "extra": True}),)
            )
        assert PLAN_TOOL in schemas
        text = messages[-1]["content"]
        return LLMReply(
            "",
            (
                ToolCall(
                    "plan",
                    PLAN_TOOL,
                    {
                        "topics": ["MAINTENANCE"],
                        "subjects": [{"entity_type": "Equipment", "reference": "e-7"}],
                        "requested_fields": ["maintenance_plans"],
                        "source_spans": [{"text": text}],
                    },
                ),
            ),
        )


class NoModel:
    def complete(self, *args, **kwargs):
        raise AssertionError("A fully resolved literal question must not call the model")


def test_u14_overlapping_terms_resolve_against_registered_identity(equipment):
    reads = ObservedReads(equipment)
    result = ReadAgent(reads, NoModel()).run(context(), request("E-7の構造上の代替候補は？"))
    assert result.answer_sections["read_outcome"] == "AUTO"
    assert "搬送装置（E-7）" in result.answer
    assert "見つかりません" not in result.answer
    assert [
        args["filter"]["reference"] for tool, args in reads.calls if tool == "search_equipment"
    ] == ["E-7", "E-7の構造上"]
    assert any(tool == "trace_downstream_impact" for tool, _ in reads.calls)


def test_u15_two_real_literal_targets_never_choose_the_first(equipment):
    with equipment.transaction() as connection:
        connection.execute(
            "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) "
            "VALUES(%s,'E-7の構造上','別の搬送装置','machine',true)",
            (UUID(int=8),),
        )
    reads = ObservedReads(equipment)
    result = ReadAgent(reads, NoModel()).run(context(), request("E-7の構造上の代替候補は？"))
    assert result.needs_input and result.answer_sections["read_outcome"] == "TARGET_AMBIGUOUS"
    assert {fact["predicate"] for fact in result.answer_sections["facts"]} == {
        "equipment.identity_candidate"
    }
    assert "搬送装置（E-7）" in result.answer and "別の搬送装置（E-7の構造上）" in result.answer
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


def test_u16_unstructured_model_plan_is_not_an_http_500(equipment):
    settings = Settings(users={"recovery-test-token": {"user_id": "manager1", "role": "manager"}})
    with TestClient(
        create_app(
            settings,
            equipment,
            llm=Plan(malformed=True),
            event_logger=EventLogger(stream=io.StringIO()),
        )
    ) as client:
        response = client.post(
            "/agent",
            headers={"Authorization": "Bearer recovery-test-token"},
            json={"message": "E-7は調子が悪い？"},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer_sections"]["read_outcome"] == "UNVERIFIABLE"
    assert data["answer_sections"]["verification"]["stage"] == "PLAN_SHAPE"
    assert data["tool_results"] == [] and data["answer_sections"]["facts"] == []


def test_u17_failed_interpretation_keeps_verified_identity_and_original_question(equipment):
    reads = ObservedReads(equipment)
    model = Plan()
    question = "e-7の点検担当者は何時に到着する？"
    result = ReadAgent(reads, model).run(context(), request(question))
    assert result.answer_sections["read_outcome"] == "UNVERIFIABLE"
    assert result.answer_sections["verification"]["stage"] == "COVERAGE_SHAPE"
    assert {fact["predicate"] for fact in result.answer_sections["facts"]} == {"equipment.identity"}
    assert "搬送装置（E-7）のことですね。" in result.answer and question in result.answer
    assert result.read_clarification is None
    assert all(tool == "search_equipment" for tool, _ in reads.calls)


def test_u18_no_product_is_not_a_completed_structural_assessment(equipment):
    reads = ObservedReads(equipment)
    result = ReadAgent(reads, NoModel()).run(context(), request("E-7の単一障害点の候補は？"))
    assert any(
        row["code"] == "ANALYSIS_TARGET_REQUIRED" for row in result.answer_sections["unavailable"]
    )
    assert "判定は実施していません" in result.answer
    assert all(tool != "find_single_point_failure_candidates" for tool, _ in reads.calls)
    assert not any(
        fact["predicate"] == "find_single_point_failure_candidates"
        for fact in result.answer_sections["facts"]
    )
