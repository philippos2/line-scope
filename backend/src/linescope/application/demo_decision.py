"""Temporary Decision Package provider for the explicit M0 demo mode.

Production facts still come from authorized PG/Graph services. Missing business
providers are placeholders, not approved capacity/economic/safety rules. No
proposal, approval or execution is performed by this analysis service.
"""

from dataclasses import dataclass

from ..domain.demo_comparison import compare
from ..domain.demo_constraints import assess_options
from ..domain.demo_scenarios import DEMO_SCENARIOS, scenario_inputs
from ..execution import ExecutionContext
from .decision_maintenance import maintenance_context
from .decision_summary import decision_summary
from .reads import ToolError


class MockDecisionProvider:
    def __init__(self, configured_scenario="AUTO"):
        if configured_scenario not in {"AUTO", *DEMO_SCENARIOS}:
            raise ValueError("Unknown configured demo scenario")
        self.configured_scenario = configured_scenario

    def read(self, equipment_code, *, scenario="STOPPED"):
        if equipment_code != "M-204":
            raise ToolError("TARGET_NOT_FOUND", "The demo fixture covers M-204 only")
        selected = scenario if self.configured_scenario == "AUTO" else self.configured_scenario
        result = compare(scenario_inputs(selected))
        result["demo_scenario"] = selected
        return result


@dataclass(frozen=True)
class DecisionAgentResult:
    data: dict
    evidence: dict
    answer: str


class DemoDecisionFlow:
    def __init__(self, reads, graph, provider, knowledge=None, llm=None):
        self.reads, self.graph, self.provider = reads, graph, provider
        self.knowledge = knowledge
        self.llm = llm

    @staticmethod
    def matches(message):
        return "M-204" in message and any(
            word in message
            for word in ("比較", "判断材料", "修理", "交換", "次回更新", "次の更新", "損失", "代替")
        )

    def run(self, context, incoming):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if context.role not in {"maintenance", "production", "manager"}:
            raise ToolError("AUTHORIZATION_DENIED", "Graph analysis permission is required")
        if incoming.explicit_as_of or incoming.replace_update_request_id:
            raise ToolError("INVALID_ARGUMENT", "The demo comparison covers current analysis only")
        if self.graph is None:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "Graph analysis is not configured")
        found = self.reads.run(
            context, "search_equipment", {"filter": {"equipment_code": "M-204"}, "page_size": 2}
        )
        equipment = found.data["items"]
        if not equipment:
            raise ToolError("TARGET_NOT_FOUND", "Equipment was not found")
        if len(equipment) != 1 or found.data["next_cursor"] is not None:
            raise ToolError("TARGET_AMBIGUOUS", "Equipment must be uniquely resolved")
        equipment_id = equipment[0]["equipment_id"]
        state = self.reads.run(context, "get_equipment_state", {"equipment_id": equipment_id})
        impact = self.graph.call(
            context,
            "trace_downstream_impact",
            {"target": {"entity_type": "Equipment", "entity_id": equipment_id}},
        )
        scenario = (
            "DEGRADED"
            if any(word in incoming.message for word in ("軽微", "次回更新", "次の更新", "30日"))
            else "STOPPED"
        )
        profile = self.provider.read("M-204", scenario=scenario)
        # Mock feasibility must never contradict the observed STOPPED state.
        if state.data["state_code"] in {"STOPPED", "UNDER_MAINTENANCE"}:
            profile["options"][-1].update(
                feasibility="INFEASIBLE",
                reason="CURRENT_EQUIPMENT_STATE_" + state.data["state_code"],
            )
        documents, document_evidence, document_status = [], {}, "NOT_CONFIGURED"
        if self.knowledge is not None:
            try:
                restored = self.knowledge.retrieve(context, {"query": "M-204 保全 修理 交換"})
                documents, document_evidence = restored.data["items"], restored.evidence
                document_status = "MOCK_SEARCH" if restored.data["demo_only"] else "VERIFIED_SOURCE"
            except ToolError as error:
                document_status = "UNAVAILABLE"
                profile["unknowns"].append("Document retrieval failed: " + error.code)
        profile.update(document_evidence=documents, document_status=document_status)
        if not documents:
            profile["unknowns"].append("No verified document evidence is available")
        assess_options(
            profile, current_state=state.data["state_code"], state_evidence=state.evidence
        )
        maintenance = maintenance_context(self.reads, context, equipment_id)
        package = {
            "equipment": {"equipment_code": "M-204", **state.data},
            "impact": impact.data,
            "comparison": profile,
            "maintenance": maintenance,
            "next_actions": {
                "prepare_message": "設備M-204の状態をUNDER_MAINTENANCEに変更して",
                "requires_explicit_request": True,
            },
        }
        summary = decision_summary(package, incoming.message, llm=self.llm)
        package["summary"] = {key: value for key, value in summary.items() if key != "answer"}
        return DecisionAgentResult(
            {"demo_only": True, "decision_package": package},
            {
                "state": state.evidence,
                "impact": impact.evidence,
                "comparison": {
                    "source": profile["source"],
                    "version": profile["fixture_version"],
                    "calculations": profile["calculations"],
                },
                "documents": document_evidence,
                "maintenance": {
                    name: maintenance[name]["evidence"] for name in ("plans", "records")
                },
                "summary": {
                    "source": summary["source"],
                    "llm_scope": summary["llm_scope"],
                    "llm_status": summary["llm_status"],
                    "facts_location": "data.decision_package",
                },
            },
            summary["answer"],
        )
