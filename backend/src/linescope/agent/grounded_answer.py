"""Build public statements from typed read results; model prose never supplies values."""

from datetime import datetime

from ..application.registered_decision import decision_answer
from ..domain.canonical import canonical_json
from .answer_text import public_answer
from .capacity_answer import capacity_answer
from .economic_answer import economic_answer
from .equipment_lookup_view import equipment_lookup_view
from .graph_answer import dependency_answer, downstream_answer, fulfillment_answer
from .maintenance_answer import maintenance_answer, maintenance_record_answer
from .read_scope import TOPICS
from .safety_answer import safety_answer
from .state_answer import state_answer

MAX_FACTS = 80
ENTITY_FIELDS = {
    "equipment": (
        "設備",
        ("equipment_name", "equipment_code", "equipment_type", "active", "version"),
    ),
    "process": ("工程", ("process_name", "process_code", "active", "version")),
    "product": ("製品", ("product_name", "product_code", "active", "version")),
    "production_operation": (
        "生産作業",
        ("operation_code", "planned_start", "planned_end", "planned_status", "version"),
    ),
    "infrastructure_resource": (
        "インフラ",
        ("resource_name", "resource_code", "resource_type", "active", "version"),
    ),
    "maintenance_plan": (
        "保全計画",
        ("plan_code", "planned_start", "planned_end", "plan_status", "version"),
    ),
    "maintenance_record": ("保全記録", ("record_code", "performed_at", "version")),
}
FIELD_LABELS = {
    "equipment_name": "名称",
    "equipment_code": "コード",
    "equipment_type": "種類",
    "process_name": "名称",
    "process_code": "コード",
    "product_name": "名称",
    "product_code": "コード",
    "resource_name": "名称",
    "resource_code": "コード",
    "resource_type": "種類",
    "operation_code": "作業コード",
    "planned_start": "予定開始",
    "planned_end": "予定終了",
    "planned_status": "登録予定状態",
    "active": "有効",
    "version": "version",
    "plan_code": "計画コード",
    "plan_status": "登録計画状態",
    "record_code": "記録コード",
    "performed_at": "登録実施日時",
}
SUMMARY_RENDERERS = {
    "get_equipment_state": (state_answer,),
    "get_capacity_input": (capacity_answer,),
    "search_capacity_inputs": (capacity_answer,),
    "get_economic_input": (economic_answer,),
    "search_economic_inputs": (economic_answer,),
    "get_safety_input": (safety_answer,),
    "search_safety_inputs": (safety_answer,),
    "get_maintenance_input": (maintenance_answer,),
    "search_maintenance_inputs": (maintenance_answer,),
    "trace_downstream_impact": (downstream_answer,),
    "trace_upstream_dependencies": (dependency_answer,),
    "find_common_dependencies": (dependency_answer,),
    "find_alternative_paths": (fulfillment_answer,),
    "find_single_point_failure_candidates": (fulfillment_answer,),
}


def shown(value):
    if value is None:
        return "未登録または不明"
    if type(value) is bool:
        return "はい" if value else "いいえ"
    return str(value) if type(value) in (str, int) else None


def search_pages(observation, observations):
    def key(item):
        return canonical_json(
            {k: v for k, v in (item.arguments or {}).items() if k not in {"cursor", "page_size"}}
        )

    pages = [o for o in observations if o.tool == observation.tool and key(o) == key(observation)]
    supplied = {(o.arguments or {}).get("cursor") for o in pages}
    pending = {o.result.data.get("next_cursor") for o in pages} - supplied - {None}
    complete = None in supplied and not pending
    rows = [row for o in pages for row in o.result.data.get("items", []) if type(row) is dict]
    return pages, rows, complete


def build_answer(observations, *, scope=None, errors=(), selected=None):
    """Only server adapters create facts. Selection names existing request-local fact IDs."""
    scope_blocked = bool(scope and scope.scope_issue)
    if scope_blocked:
        observations = ()
    facts, unavailable = [], []
    truncated = False

    def missing(code, text, references=()):
        item = {"code": code, "text": text, "references": list(references)}
        if item not in unavailable:
            unavailable.append(item)

    def add(kind, text, references, predicate):
        nonlocal truncated
        text = public_answer(text, observations)
        for fact in facts:
            if fact["kind"] == kind and fact["predicate"] == predicate and fact["text"] == text:
                fact["references"] = list(dict.fromkeys([*fact["references"], *references]))
                return
        if len(facts) >= MAX_FACTS:
            truncated = True
            return
        facts.append(
            {
                "id": "f" + str(len(facts) + 1),
                "kind": kind,
                "predicate": predicate,
                "text": text,
                "references": list(references),
            }
        )

    identity = tuple(o for o in observations if o.tool in {"search_equipment", "get_equipment"})
    lookup_groups = equipment_lookup_view(identity)
    record_queries = set()
    for observation in observations:
        if observation.tool != "search_maintenance_records":
            continue
        pages, records, complete = search_pages(observation, observations)
        key = tuple(o.tool_call_id for o in pages)
        if key in record_queries or not records:
            continue
        record_queries.add(key)
        try:
            dates = [
                datetime.fromisoformat(row["performed_at"].replace("Z", "+00:00"))
                for row in records
            ]
            if not all(value.tzinfo is not None for value in dates):
                raise ValueError("Timezone required")
        except (KeyError, AttributeError, TypeError, ValueError):
            missing("INVALID_RESULT", "保全記録の実施日時を確認できません。", key)
            continue
        qualification = (
            "今回の検索条件の登録記録"
            if complete and not errors
            else "取得済み範囲の登録記録（全件は未確認）"
        )
        add(
            "SEARCH_RESULT",
            qualification
            + "の実施日時の最大値："
            + records[max(range(len(dates)), key=dates.__getitem__)]["performed_at"]
            + "。実際の全保全作業を網羅した日時とは限りません。",
            key,
            "maintenance_record.max_registered_date",
        )
    for observation in observations:
        tool, data = observation.tool, observation.result.data
        refs = (observation.tool_call_id,)
        matched = False
        if data.get("not_evaluated"):
            missing(
                "NOT_EVALUATED",
                "この取得結果に未評価の観点があります。登録された関係・判定だけから、実際の運転可否・能力・安全性等は判断できません。",
                refs,
            )
        for entity, (label, fields) in ENTITY_FIELDS.items():
            if tool not in {"get_" + entity, "search_" + entity + "s"}:
                # Irregular plurals are explicit data contracts, not natural-language rules.
                if not (entity == "equipment" and tool == "search_equipment"):
                    continue
            matched = True
            rows = data.get("items", []) if tool.startswith("search_") else [data]
            if type(rows) is not list:
                missing("INVALID_RESULT", "取得結果の形式を確認できません。", refs)
                break
            for row in rows:
                if type(row) is not dict:
                    continue
                values = []
                for field in fields:
                    if field in row and (value := shown(row[field])) is not None:
                        values.append(FIELD_LABELS[field] + "：" + value)
                subject = " · ".join(
                    str(row[k])
                    for k in fields
                    if k.endswith(("_name", "_code")) and type(row.get(k)) is str
                )
                if values:
                    add(
                        "REGISTERED_FIELD",
                        f"登録{label}「{subject or label}」：" + "、".join(values) + "。",
                        refs,
                        entity + ".registered_fields",
                    )
            if tool.startswith("search_"):
                _, all_rows, complete = search_pages(observation, observations)
                if not complete:
                    missing(
                        "INCOMPLETE",
                        f"{label}の検索の続きは未取得です。全件・一意・最新は確定していません。",
                        refs,
                    )
                elif (
                    not all_rows
                    and not errors
                    and not (
                        tool == "search_equipment"
                        and any(
                            group["equipment_found"]
                            and any(
                                query["filter"] == (observation.arguments or {}).get("filter", {})
                                for query in group["queries"]
                            )
                            for group in lookup_groups
                        )
                    )
                ):
                    missing(
                        "NO_MATCH",
                        f"今回の検索条件で{label}の登録は0件です。他の条件や実際の存在を否定するものではありません。",
                        refs,
                    )
                if entity == "equipment" and len(rows) > 1:
                    missing(
                        "AMBIGUOUS",
                        "設備候補が複数あります。対象を選択するまで同一設備とは確定しません。",
                        refs,
                    )
            break
        if tool == "retrieve_knowledge":
            items = data.get("items", [])
            add(
                "DOCUMENT_REFERENCE",
                f"正本で確認した文書抜粋を{len(items)}件取得しました。文書は参考情報であり、設備の実状態・安全・費用の確定判定ではありません。原文と出典は取得結果を参照してください。",
                refs,
                "knowledge.verified_excerpt",
            )
            if data.get("complete") is not True:
                missing(
                    "INCOMPLETE",
                    "文書検索は候補検索であり、全ての関連文書を網羅した結果ではありません。",
                    refs,
                )
            matched = True
        if tool == "search_maintenance_records":
            summary = maintenance_record_answer((*identity, observation), has_errors=bool(errors))
            if summary:
                add("SEARCH_RESULT", summary, refs, "maintenance_record.search_scope")
        renderers = SUMMARY_RENDERERS.get(tool, ())
        summary = None
        for render in renderers:
            try:
                summary = render((*identity, observation), has_errors=bool(errors))
            except (KeyError, TypeError, ValueError):
                summary = None
            if summary:
                break
        if tool == "compare_registered_inputs":
            try:
                summary = decision_answer(data)
            except (KeyError, TypeError, ValueError):
                summary = None
        if summary:
            add("SERVER_ASSESSMENT", summary, refs, tool)
        elif renderers or tool == "compare_registered_inputs":
            missing(
                "UNVERIFIABLE_RESULT",
                "取得した判定の前提・形式を確認できないため、結論は表示していません。",
                refs,
            )
        elif not matched:
            # A supported tool without a public typed renderer is not a licence for model prose.
            missing(
                "NO_PUBLIC_RENDERER",
                "この取得結果を事実として説明する公開形式が未対応です。出典と構造化結果を確認してください。",
                refs,
            )

    if errors:
        missing(
            "READ_FAILED",
            "一部の登録情報を取得できませんでした。取得失敗を未登録や記録なしとは判断していません。",
        )
    topics = scope.topics if scope and not scope_blocked else ()
    for topic in topics:
        required = TOPICS[topic][1]
        if topic == "UNSUPPORTED":
            missing(
                "OUT_OF_SCOPE",
                "この版で参照できる情報の範囲外の事項があります。登録の有無や、その値・場所・可否は判断できません。",
            )
        elif required and not any(o.tool in required for o in observations):
            missing(
                "NOT_RETRIEVED",
                f"{TOPICS[topic][0]}に必要な情報は取得できていません。対象の識別だけでは回答できません。",
            )
    if truncated:
        missing(
            "DISPLAY_LIMIT",
            "表示上限に達しています。省略された情報を含む全体の結論は確定していません。",
        )
    if selected is not None:
        ids = {f["id"] for f in facts}
        if (
            type(selected) is not dict
            or set(selected) != {"fact_ids"}
            or type(selected.get("fact_ids")) is not list
            or len(selected["fact_ids"]) > MAX_FACTS
            or any(type(value) is not str or value not in ids for value in selected["fact_ids"])
            or len(set(selected["fact_ids"])) != len(selected["fact_ids"])
        ):
            missing(
                "INVALID_SELECTION",
                "回答と取得根拠の対応を確認できません。モデルが指定した主張は表示していません。",
            )
        else:
            # A model may order verified facts, but cannot hide a result or its limitations.
            order = {value: i for i, value in enumerate(selected["fact_ids"])}
            facts.sort(key=lambda fact: order.get(fact["id"], MAX_FACTS))
    if scope_blocked:
        missing(
            "QUESTION_SCOPE_UNCONFIRMED",
            "質問で求められた情報と、参照できる情報の対応を確認できません。"
            "別の情報を質問への回答として表示することはしていません。"
            "登録の有無や値は未確認です。この質問への回答は確定できません。",
        )
    elif not observations and topics != ("UNSUPPORTED",):
        missing(
            "NOT_RETRIEVED",
            "参照結果は取得していません。対象や質問の範囲を具体的に指定してください。",
        )
    scope_labels = scope.labels() if scope else []
    if scope_blocked:
        scope_labels = ["質問との対応を確認できなかった解釈：" + "、".join(scope_labels)]
    if scope and scope.subjects:
        subjects = "、".join(subject["reference"] for subject in scope.subjects)
        scope_labels = [public_answer(f"抽出した対象表現：{subjects}", observations), *scope_labels]
    sections = {
        "version": 1,
        "mode": "REGISTERED_RESULTS",
        "scope": scope_labels,
        "facts": facts,
        "interpretation": [],
        "unavailable": unavailable,
        "notice": "AIは質問の解釈と情報の整理を担当します。事実は取得した登録情報からサーバが表示しています。",
    }
    paragraphs = [fact["text"] for fact in facts] + [item["text"] for item in unavailable]
    return "\n".join(paragraphs), sections
