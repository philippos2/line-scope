"""Typed demo reads and deterministic public text, extracted from archived H7.

No natural-language classification or LLM is reachable from this executor.
"""

from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from ..application.reads import ReadResult, ToolError
from .agent_tools import AgentToolSession
from .graph_answer import dependency_answer, downstream_answer, fulfillment_answer
from .read_agent import ReadAgentResult, ReadObservation

GET_ENTITY = {
    "Equipment": ("get_equipment", "equipment_id", "equipment_name", "equipment_code"),
    "Process": ("get_process", "process_id", "process_name", "process_code"),
    "Product": ("get_product", "product_id", "product_name", "product_code"),
    "ProductionOperation": (
        "get_production_operation",
        "production_operation_id",
        None,
        "operation_code",
    ),
    "InfrastructureResource": (
        "get_infrastructure_resource",
        "infrastructure_resource_id",
        "resource_name",
        "resource_code",
    ),
}


def valid(observation):
    data, evidence, args = (
        observation.result.data,
        observation.result.evidence,
        observation.arguments,
    )
    if not isinstance(data, dict) or not isinstance(evidence, dict):
        return False
    if evidence.get("tool") != observation.tool or not evidence.get("source"):
        return False
    if evidence.get("tool_call_id", observation.tool_call_id) != observation.tool_call_id:
        return False
    try:
        at = evidence.get("observed_at", evidence.get("graph_observed_at"))
        if (
            not isinstance(at, str)
            or datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is None
        ):
            return False
    except ValueError:
        return False
    for key, value in args.items():
        if key.endswith("_id") and data.get(key) != value:
            return False
        if key == "target" and data.get(key) != value:
            return False
    if args.get("filter", {}).get("equipment_id"):
        items = data.get("items")
        if type(items) is not list or any(
            type(row) is not dict or row.get("equipment_id") != args["filter"]["equipment_id"]
            for row in items
        ):
            return False
    return True


def response(text, outcome, observations=(), *, needs_input=False, errors=(), key=None):
    facts = (
        []
        if not observations
        else [
            {
                "id": "f1",
                "kind": "REGISTERED_FIELD",
                "text": text,
                "references": [o.tool_call_id for o in observations],
            }
        ]
    )
    return ReadAgentResult(
        text,
        tuple(observations),
        tuple(
            {"tool_call_id": o.tool_call_id, "tool": o.tool, "attempt": 1, "code": "OK"}
            for o in observations
        ),
        tuple(errors),
        needs_input,
        {
            "version": 1,
            "read_outcome": outcome,
            "selected_field": key,
            "facts": facts,
            "unavailable": [],
            "scope": [],
        },
    )


def alternative_answer(data, target, label, read):
    """Name only candidates from the requested replacement result, using verified reads."""
    groups = data.get("alternatives")
    if (
        data.get("excluded_nodes") != [target]
        or type(groups) is not list
        or len(groups) != 1
        or type(groups[0]) is not dict
        or groups[0].get("excluded_node") != target
        or type(groups[0].get("candidates")) is not list
    ):
        raise ToolError("INTERNAL_ERROR", "Alternative result target mismatch")
    candidates = groups[0]["candidates"]
    established, rejected, unknown, seen = [], [], [], set()
    for item in candidates:
        if (
            type(item) is not dict
            or type(item.get("candidate")) is not dict
            or type(item.get("structure")) is not dict
        ):
            raise ToolError("INTERNAL_ERROR", "Invalid replacement shape")
        node = item.get("candidate", {})
        structure = item.get("structure", {}).get("determination")
        availability = item.get("availability")
        if (
            node.get("entity_type") != "Equipment"
            or node == target
            or structure not in {"ESTABLISHED", "NOT_ESTABLISHED", "INDETERMINATE"}
            or availability not in {"AVAILABLE", "UNAVAILABLE", "UNKNOWN"}
        ):
            raise ToolError("INTERNAL_ERROR", "Invalid replacement candidate")
        identity = str(UUID(node["entity_id"]))
        if identity in seen:
            raise ToolError("INTERNAL_ERROR", "Duplicate replacement candidate")
        seen.add(identity)
        if len(seen) > 12:
            continue
        equipment = read("get_equipment", {"equipment_id": identity})
        if not all(
            isinstance(equipment.get(field), str) and equipment[field].strip()
            for field in ("equipment_name", "equipment_code")
        ):
            raise ToolError("INTERNAL_ERROR", "Invalid candidate name")
        name = f"{equipment['equipment_name']}（{equipment['equipment_code']}）"
        if not data["complete"] or structure == "INDETERMINATE":
            unknown.append(name)
        elif structure == "NOT_ESTABLISHED":
            rejected.append(name)
        else:
            if availability == "UNAVAILABLE":
                name += "（登録状態では利用不可）"
            elif availability == "UNKNOWN":
                name += "（登録状態による利用可否は不明）"
            established.append(name)
    scope = "表示した候補" if len(candidates) > 12 else "今回の探索範囲"
    text = (
        f"{label}の構造上の代替候補は、" + "、".join(established) + "です。"
        if established
        else f"{label}について、{scope}では構造上の代替候補の成立を確認できませんでした。"
    )
    if rejected:
        text += (
            "登録された代替関係にある"
            + "、".join(rejected)
            + "は、構造条件が成立しないため、成立した候補には含めません。"
        )
    if unknown:
        text += "構造成立を確認できない登録候補：" + "、".join(unknown) + "。"
    if not candidates and data["complete"]:
        text += "登録された関係から候補は見つかりませんでした。実際に代替設備が存在しないと断定したものではありません。"
    if not data["complete"]:
        text += (
            "探索は不完全で、候補の全件や構造成立を確定できません。候補なしとは判断していません。"
        )
    if len(candidates) > 12:
        text += "候補名は先頭12件だけを表示しています。"
    return (
        text
        + "ただし、実際に代替運転できるかは未評価です。能力・安全性・経済影響も評価していません。"
    )


class RegisteredQuestionReads:
    def __init__(self, dispatcher, *, event_logger=None, deadline_seconds=60):
        self.dispatcher, self.events, self.deadline = dispatcher, event_logger, deadline_seconds

    def session(self, context, request):
        return AgentToolSession(
            context,
            replace(request, message="登録情報の照会", context_id=None),
            self.dispatcher,
            max_calls=64,
            event_logger=self.events,
            deadline_seconds=self.deadline,
        )

    def run(self, context, request, key, equipment_id):
        session, observations = self.session(context, request), []

        def read(tool, args):
            call_id = str(uuid4())
            result = session.run(tool, args, tool_call_id=call_id)
            item = ReadObservation(call_id, tool, result, args)
            if not isinstance(result, ReadResult) or not valid(item):
                raise ToolError("INTERNAL_ERROR", "Read result does not match request or evidence")
            observations.append(item)
            return result.data

        try:
            equipment = read("get_equipment", {"equipment_id": equipment_id})
            label = f"{equipment['equipment_name']}（{equipment['equipment_code']}）"
            target = {"entity_type": "Equipment", "entity_id": equipment_id}
            if key in {"equipment_name", "equipment_code", "equipment_type"}:
                if not isinstance(equipment.get(key), str):
                    raise ToolError("INTERNAL_ERROR", "Selected attribute missing")
                text = f"{label}の登録された情報は『{equipment[key]}』です。"
            elif key == "registered_state":
                row = read("get_equipment_state", {"equipment_id": equipment_id})
                labels = {
                    "RUNNING": "稼働中",
                    "STOPPED": "停止中",
                    "UNDER_MAINTENANCE": "保全中",
                    "UNKNOWN": "不明",
                }
                if row.get("state_code") not in labels:
                    raise ToolError("INTERNAL_ERROR", "Selected state missing")
                text = f"{label}は、登録上は{labels[row['state_code']]}です。現在の実稼働状態を確認したものではなく、故障原因や安全性もこの情報からは判断できません。"
            elif key in {"maintenance_records", "maintenance_plans"}:
                tool = "search_" + key
                rows, cursor, seen = [], None, set()
                for _ in range(12):
                    page = read(
                        tool,
                        {
                            "filter": {"equipment_id": equipment_id},
                            "page_size": 100,
                            "cursor": cursor,
                        },
                    )
                    rows.extend(page["items"])
                    cursor = page.get("next_cursor")
                    if cursor is None:
                        break
                    if cursor in seen:
                        raise ToolError("INTERNAL_ERROR", "Repeated cursor")
                    seen.add(cursor)
                complete = cursor is None
                noun = "保全実績" if key == "maintenance_records" else "保全計画"
                if not rows and complete:
                    text = f"{label}の{noun}は登録されていません。実際に保全が未実施という意味ではありません。"
                else:
                    field = "performed_at" if key == "maintenance_records" else "planned_start"
                    for row in rows:
                        if not isinstance(row.get(field), str):
                            raise ToolError("INTERNAL_ERROR", "Selected record time missing")
                    rows.sort(key=lambda row: row[field], reverse=True)
                    details = [
                        f"{row.get('record_code', row.get('plan_code', '記録'))}：{row[field]}"
                        for row in rows[:6]
                    ]
                    text = f"{label}の登録済み{noun}は、" + "、".join(details) + "です。"
                    if not complete:
                        text += "検索は不完全です。最新や全件とは判断できません。"
                    elif rows and key == "maintenance_records":
                        text += f"登録記録で最も新しい実施日時は{rows[0][field]}です。実作業全体の網羅を保証しません。"
                    if len(rows) > 6:
                        text += "本文は先頭6件を表示しています。"
            elif key in {
                "downstream_reachability",
                "upstream_dependencies",
                "alternative_candidates",
            }:
                tool = (
                    "trace_upstream_dependencies"
                    if key == "upstream_dependencies"
                    else "trace_downstream_impact"
                )
                graph = read(tool, {"target": target})
                if key == "alternative_candidates":
                    products = [
                        node
                        for node in graph.get("reached_nodes", [])
                        if node.get("entity_type") == "Product"
                    ]
                    if not graph.get("complete") or not products:
                        text = f"{label}の構造上の代替候補を評価するための製品範囲を確定できません。代替設備が存在しないという意味ではありません。"
                    else:
                        alternatives = read(
                            "find_alternative_paths",
                            {"important_targets": products, "excluded_nodes": [target]},
                        )
                        chosen = [o for o in observations if o.tool == "find_alternative_paths"]
                        summary = fulfillment_answer(chosen)
                        if not summary:
                            raise ToolError("INTERNAL_ERROR", "Invalid alternative result")
                        try:
                            if sorted(
                                alternatives.get("important_targets", []),
                                key=lambda n: (n["entity_type"], n["entity_id"]),
                            ) != sorted(products, key=lambda n: (n["entity_type"], n["entity_id"])):
                                raise ToolError("INTERNAL_ERROR", "Alternative product mismatch")
                            text = alternative_answer(alternatives, target, label, read)
                        except ToolError as error:
                            return response(
                                "代替候補の情報・名称を取得または検証できませんでした。候補がないとは判断していません。時間をおいて同じ質問を送ってください。",
                                "READ_FAILED",
                                errors=(error.as_dict(),),
                                key=key,
                            )
                else:
                    chosen = [o for o in observations if o.tool == tool]
                    summary = (
                        dependency_answer(chosen, include_detail_link=False)
                        if key == "upstream_dependencies"
                        else downstream_answer(chosen, include_detail_link=False)
                    )
                    if not summary:
                        raise ToolError("INTERNAL_ERROR", "Invalid graph result")
                    names = []
                    for node in graph.get("reached_nodes", [])[:12]:
                        getter, field, name, code = GET_ENTITY[node["entity_type"]]
                        row = read(getter, {field: node["entity_id"]})
                        names.append(
                            " · ".join(str(row[k]) for k in (name, code) if k and row.get(k))
                        )
                    text = label + "について、" + summary
                    if names:
                        text += " 登録関係で到達する対象：" + "、".join(names) + "。"
                    if len(graph.get("reached_nodes", [])) > 12:
                        text += "対象名は先頭12件を表示しています。"
            else:
                raise ToolError("INVALID_ARGUMENT", "Unknown demo viewpoint")
            public = []
            for item in observations:
                if item.tool.startswith("get_") and item.tool != "get_equipment_state":
                    fields = {"equipment_id", "equipment_name", "equipment_code", key}
                    for getter, identifier, name, code in GET_ENTITY.values():
                        if getter == item.tool:
                            fields = {identifier, name, code} | (
                                {key} if getter == "get_equipment" else set()
                            )
                    item = replace(
                        item,
                        result=ReadResult(
                            {k: v for k, v in item.result.data.items() if k in fields},
                            item.result.evidence,
                        ),
                    )
                public.append(item)
            return response(text, "ANSWERED", public, key=key)
        except ToolError as error:
            return response(
                "登録情報を取得・検証できませんでした。未登録や影響なしとは判断していません。時間をおいて、同じ質問をもう一度送ってください。",
                "READ_FAILED",
                errors=(error.as_dict(),),
                key=key,
            )
