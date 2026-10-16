"""Authorized, explicitly selected inputs; no mock provider or writes."""

import re
from dataclasses import dataclass

from ..domain.canonical import strict_json
from ..domain.decision import comparison, normalize_selection
from ..domain.safety import calculate as safety_calculation
from .capacity import CapacityInputs
from .economics import EconomicInputs
from .maintenance_inputs import MaintenanceInputs
from .proposals import ProposalError
from .reads import ReadTools, ToolError, json_value
from .safety import SafetyInputs, require


@dataclass(frozen=True)
class DecisionAgentResult:
    data: dict
    evidence: dict
    answer: str


class RegisteredDecisions:
    def __init__(self, database, graph, knowledge=None):
        self.reads, self.graph = ReadTools(database), graph
        self.knowledge = knowledge
        self.economics, self.capacity = EconomicInputs(database), CapacityInputs(database)
        self.safety, self.maintenance = SafetyInputs(database), MaintenanceInputs(database)

    def compare(self, context, values):
        require(context)
        try:
            v = normalize_selection(values)
        except (TypeError, ValueError) as error:
            raise ProposalError(
                "INVALID_ARGUMENT", "Invalid registered comparison selection"
            ) from error
        economic = (
            self.economics.get(context, v["economic_input_id"]) if v["economic_input_id"] else None
        )
        capacities = [
            self.capacity.get(context, identifier) for identifier in v["capacity_input_ids"]
        ]
        safety = [self.safety.get(context, identifier) for identifier in v["safety_input_ids"]]
        maintenance = [
            self.maintenance.get(context, identifier) for identifier in v["maintenance_input_ids"]
        ]
        if any(row["input"]["equipment_id"] == v["equipment_id"] for row in capacities):
            raise ProposalError(
                "BUSINESS_RULE_VIOLATION",
                "Select alternate equipment capacity, not self substitution",
            )
        allowed = {v["equipment_id"], *(row["input"]["equipment_id"] for row in capacities)}
        for row in ([economic] if economic else []) + capacities + safety + maintenance:
            record, p = row["input"], row["input"]["payload"]
            if (
                record["equipment_id"] not in allowed
                or (row in maintenance or row is economic)
                and record["equipment_id"] != v["equipment_id"]
            ):
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Selected input equipment mismatch")
            if row in maintenance and p["kind"].endswith("_RECORD"):
                continue  # Historical context is never added to future option cost.
            if row in safety:
                if p["period_start"] > v["period_start"] or p["period_end"] < v["period_end"]:
                    raise ProposalError(
                        "BUSINESS_RULE_VIOLATION", "Safety input must cover the comparison period"
                    )
                row["calculation"] = safety_calculation(p, v["period_start"])
            elif (p["period_start"], p["period_end"]) != (v["period_start"], v["period_end"]):
                raise ProposalError("BUSINESS_RULE_VIOLATION", "Common comparison period required")
        plan_kinds = [
            row["input"]["payload"]["kind"]
            for row in maintenance
            if row["input"]["payload"]["kind"].endswith("_PLAN")
        ]
        if len(set(plan_kinds)) != len(plan_kinds):
            raise ProposalError("INVALID_ARGUMENT", "Select one plan per option")
        states, impact, upstream, equipment = self.facts(context, v["equipment_id"], allowed)
        profile = comparison(economic, capacities, safety, maintenance, states)
        package = {
            "equipment": {**equipment.data, **states[0]["data"]},
            "impact": impact.data,
            "upstream_dependencies": upstream.data,
            "comparison": profile,
            "selected_inputs": {
                "economic": economic,
                "capacity": capacities,
                "safety": safety,
                "maintenance": maintenance,
            },
            "comparison_period": {"start": v["period_start"], "end": v["period_end"]},
            "consistency": "LATEST_PER_CALL",
            "selection": v,
            "automatic_state_change": False,
        }
        evidence = {
            "impact": impact.evidence,
            "upstream_dependencies": upstream.evidence,
            "states": states,
            "registered_inputs": [
                {"source": "POSTGRESQL", "observed_at": row["observed_at"], "input": row["input"]}
                for row in ([economic] if economic else []) + capacities + safety + maintenance
            ],
        }
        return json_value(
            {"source": "REGISTERED_INPUT", "decision_package": package, "evidence": evidence}
        )

    def facts(self, context, identifier, allowed):
        equipment = self.reads.run(context, "get_equipment", {"equipment_id": identifier})
        states = []
        for current in [identifier, *sorted(allowed - {identifier})]:
            state = self.reads.run(context, "get_equipment_state", {"equipment_id": current})
            states.append({"equipment_id": current, "data": state.data, "evidence": state.evidence})
        if self.graph is None:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "Graph analysis is not configured")
        impact = self.graph.call(
            context,
            "trace_downstream_impact",
            {"target": {"entity_type": "Equipment", "entity_id": identifier}},
        )
        upstream = self.graph.call(
            context,
            "trace_upstream_dependencies",
            {"target": {"entity_type": "Equipment", "entity_id": identifier}},
        )
        if impact.evidence["graph_generation"] != upstream.evidence["graph_generation"]:
            raise ToolError("GRAPH_NOT_CURRENT", "Graph generation changed; retry the analysis")
        return states, impact, upstream, equipment

    @staticmethod
    def matches(message):
        return message.startswith("登録入力で比較 ") or bool(
            re.search(r"[A-Za-z][A-Za-z0-9]*-\d+", message)
            and "比較" in message
            and not any(
                word in message
                for word in (
                    "経済入力",
                    "能力入力",
                    "安全入力",
                    "対応計画",
                    "故障履歴",
                    "economic_input",
                    "capacity_input",
                    "safety_input",
                    "maintenance_input",
                    "入力ID",
                    "履歴ID",
                    "変更して",
                )
            )
        )

    def run(self, context, incoming):
        require(context)
        if incoming.explicit_as_of or incoming.context_id or incoming.replace_update_request_id:
            raise ToolError("INVALID_ARGUMENT", "Start a new explicit registered comparison")
        try:
            if incoming.message.startswith("登録入力で比較 "):
                data = self.compare(
                    context, strict_json(incoming.message.removeprefix("登録入力で比較 "))
                )
                return DecisionAgentResult(data, data["evidence"], decision_answer(data))
            codes = set(re.findall(r"[A-Za-z][A-Za-z0-9]*-\d+", incoming.message))
            if len(codes) != 1:
                raise ToolError("TARGET_AMBIGUOUS", "Select one equipment")
            result = self.reads.run(
                context,
                "search_equipment",
                {"filter": {"equipment_code": codes.pop()}, "page_size": 2},
            )
            if len(result.data["items"]) != 1:
                raise ToolError(
                    "TARGET_NOT_FOUND" if not result.data["items"] else "TARGET_AMBIGUOUS",
                    "Select registered equipment",
                )
            identifier = result.data["items"][0]["equipment_id"]
            candidates = {
                name: service.search(
                    context, {"filter": {"equipment_id": identifier}, "page_size": 20}
                )
                for name, service in (
                    ("economic", self.economics),
                    ("capacity", self.capacity),
                    ("safety", self.safety),
                    ("maintenance", self.maintenance),
                )
            }
            states, impact, upstream, equipment = self.facts(context, identifier, {identifier})
            profile = comparison(None, [], [], [], states)
            profile.update(document_evidence=[], document_status="NOT_CONFIGURED")
            document_evidence = {}
            if self.knowledge is not None:
                try:
                    documents = self.knowledge.retrieve(
                        context, {"query": equipment.data["equipment_code"] + " 保全 修理 交換"}
                    )
                    profile.update(
                        document_evidence=documents.data["items"],
                        document_status="MOCK_SEARCH"
                        if documents.data["demo_only"]
                        else "VERIFIED_SOURCE",
                    )
                    document_evidence = documents.evidence
                except ToolError:
                    profile["document_status"] = "UNAVAILABLE"
            from .decision_maintenance import maintenance_context

            maintenance = maintenance_context(self.reads, context, identifier)
            evidence = {
                "equipment": equipment.evidence,
                "state": states[0]["evidence"],
                "impact": impact.evidence,
                "upstream_dependencies": upstream.evidence,
                "documents": document_evidence,
                "maintenance": {
                    name: maintenance[name]["evidence"] for name in ("plans", "records")
                },
            }
            package = {
                "equipment": {**equipment.data, **states[0]["data"]},
                "impact": impact.data,
                "upstream_dependencies": upstream.data,
                "comparison": profile,
                "maintenance": maintenance,
                "comparison_period": None,
                "next_actions": {
                    "prepare_message": "設備"
                    + equipment.data["equipment_code"]
                    + "の状態をUNDER_MAINTENANCEに変更して",
                    "requires_explicit_request": True,
                },
            }
            return DecisionAgentResult(
                json_value(
                    {
                        "source": "REGISTERED_INPUT",
                        "selection_required": True,
                        "equipment_id": identifier,
                        "candidates": candidates,
                        "tool_results": [{"tool": "search_equipment", "data": result.data}],
                        "decision_package": package,
                    }
                ),
                json_value(evidence),
                "正式入力の候補を取得しました。比較期間と各入力を選択してください。未登録の費用・能力・安全条件を仮値で補完しません。"
                + decision_answer({"decision_package": package}),
            )

        except ProposalError as error:
            raise ToolError(error.code, error.message) from error
        except (ValueError, TypeError) as error:
            raise ToolError("INVALID_ARGUMENT", "Invalid registered comparison") from error


def decision_answer(data):
    profile = data["decision_package"]["comparison"]
    excluded = [row["option"] for row in profile["options"] if row["feasibility"] == "INFEASIBLE"]
    return (
        "登録済み入力と共通期間による比較です。"
        + "上流依存は設備が依存する資源であり、設備停止による被影響対象ではありません。"
        + (
            "現在状態・停止必須・能力制約により候補から除外：" + "、".join(excluded) + "。"
            if excluded
            else ""
        )
        + "費用は出典付きの登録値から計算し、調達待ち・作業・停止時間と過去損失を区別しています。未登録値を仮値で補完せず、実行可能性・設備全体の安全・最適案は認定しません。"
    )
