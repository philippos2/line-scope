"""Temporary Decision Package provider for the explicit M0 demo mode.

Production facts still come from authorized PG/Graph services. Missing business
providers are placeholders, not approved capacity/economic/safety rules. No
proposal, approval or execution is performed by this analysis service.
"""

from copy import deepcopy
from dataclasses import dataclass

from ..execution import ExecutionContext
from .reads import ToolError

# Hand-checkable temporary fixture. Values are not business database facts and
# do not constitute BS-G01 acceptance. Replace this provider on the same path.
MOCK_PROFILE = {
    "source": "MOCK_FIXTURE",
    "fixture_version": "decision-flow-demo:v1",
    "economics": {
        "currency": "JPY",
        "product_loss_per_hour": {"P-100": 120000, "P-200": 80000},
        "independent_addition": True,
        "loss_per_hour": 200000,
    },
    "options": [
        {
            "option": "REPAIR",
            "feasibility": "MOCK_FEASIBLE",
            "direct_cost": 300000,
            "duration_hours": 8,
            "production_loss": 1600000,
            "total_cost": 1900000,
            "formula": "(120000 + 80000) * 8 + 300000",
        },
        {
            "option": "REPLACE",
            "feasibility": "MOCK_FEASIBLE",
            "direct_cost": 3000000,
            "lead_time_days": 14,
            "duration_hours": None,
            "production_loss": None,
            "total_cost": None,
        },
        {
            "option": "SUBSTITUTE",
            "feasibility": "UNKNOWN",
            "equipment_code": "M-208",
            "required_units_per_hour": 90,
            "available_units_per_hour": 60,
            "shortage_units_per_hour": 30,
            "formula": "90 - 60",
        },
        {"option": "CONTINUE", "feasibility": "UNKNOWN", "safety_permission": "UNKNOWN"},
    ],
    "risk": {
        dimension: "UNKNOWN"
        for dimension in ("SAFETY", "PRODUCTION", "QUALITY", "DELIVERY", "CASCADE", "ECONOMIC")
    },
    "document_evidence": [
        {
            "source": "MOCK_FIXTURE",
            "reference": "mock-maintenance-manual",
            "text": "修理・交換・継続・代替を比較するための仮置き資料。実文書検索は未接続。",
        }
    ],
    "unknowns": [
        "Actual capacity, costs and safety rules are not registered",
        "Replacement work duration and downtime loss are unknown",
        "Continued-operation safety permission is unknown",
        "Document retrieval is a temporary mock",
    ],
}


class MockDecisionProvider:
    def read(self, equipment_code):
        if equipment_code != "M-204":
            raise ToolError("TARGET_NOT_FOUND", "The demo fixture covers M-204 only")
        return deepcopy(MOCK_PROFILE)


@dataclass(frozen=True)
class DecisionAgentResult:
    data: dict
    evidence: dict
    answer: str


class DemoDecisionFlow:
    def __init__(self, reads, graph, provider):
        self.reads, self.graph, self.provider = reads, graph, provider

    @staticmethod
    def matches(message):
        return "M-204" in message and any(
            word in message for word in ("比較", "判断材料", "修理", "交換")
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
        profile = self.provider.read("M-204")
        # Mock feasibility must never contradict the observed STOPPED state.
        if state.data["state_code"] == "STOPPED":
            profile["options"][-1].update(
                feasibility="INFEASIBLE", reason="CURRENT_EQUIPMENT_STATE_STOPPED"
            )
        package = {
            "equipment": {"equipment_code": "M-204", **state.data},
            "impact": impact.data,
            "comparison": profile,
            "next_actions": {
                "prepare_message": "設備M-204の状態をUNDER_MAINTENANCEに変更して",
                "requires_explicit_request": True,
            },
        }
        return DecisionAgentResult(
            {"demo_only": True, "decision_package": package},
            {
                "state": state.evidence,
                "impact": impact.evidence,
                "comparison": {"source": profile["source"], "version": profile["fixture_version"]},
            },
            f"M-204の現在状態は{state.data['state_code']}です。登録された依存関係の影響候補を取得しました。"
            "費用・能力・リスク・文書はモックの仮置きです。実際の安全性や最適案は未確定です。"
            "変更する場合は、明示的な変更準備要求から承認・実行へ進んでください。",
        )
