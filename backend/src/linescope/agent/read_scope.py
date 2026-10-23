"""Question interpretation selects capabilities, never facts or authority."""

from dataclasses import dataclass
from time import monotonic

from ..application.reads import ToolError
from ..domain.canonical import canonical_json
from ..integrations.llm import LLMError, LLMReply
from .equipment_reference import question_messages, reference_key

PLAN_TOOL = "describe_read_request"
SELECT_TOOL = "select_answer_facts"
IDENTITY_TOOLS = {
    "search_equipment",
    "get_equipment",
    "get_process",
    "get_product",
    "get_production_operation",
    "get_infrastructure_resource",
}
TOPICS = {
    "ATTRIBUTES": ("登録属性", set()),
    "STATE": ("登録上の設備状態", {"get_equipment_state"}),
    "MAINTENANCE": (
        "保全の計画・実績",
        {"get_maintenance_plan", "search_maintenance_plans", "search_maintenance_records"},
    ),
    "UPSTREAM": (
        "上流の依存関係",
        {
            "trace_upstream_dependencies",
            "search_dependency_relations",
            "get_dependency_relation",
            "get_operation_equipment_assignments",
        },
    ),
    "DOWNSTREAM": ("下流への影響範囲", {"trace_downstream_impact"}),
    "ALTERNATIVES": ("構造上の代替候補", {"find_alternative_paths"}),
    "COMMON_DEPENDENCIES": ("共通の依存先", {"find_common_dependencies"}),
    "SINGLE_POINT_FAILURE": ("単一障害点の候補", {"find_single_point_failure_candidates"}),
    "ECONOMICS": ("登録した損害・費用", {"search_economic_inputs", "get_economic_input"}),
    "CAPACITY": ("登録した能力", {"search_capacity_inputs", "get_capacity_input"}),
    "SAFETY": ("選択した安全条件", {"search_safety_inputs", "get_safety_input"}),
    "MAINTENANCE_INPUTS": (
        "登録した対応計画・故障履歴",
        {"search_maintenance_inputs", "get_maintenance_input"},
    ),
    "COMPARISON": ("明示選択した入力による対応案比較", {"compare_registered_inputs"}),
    "DOCUMENTS": ("正本で確認した関連文書", {"retrieve_knowledge"}),
    "UNSUPPORTED": ("この版の参照範囲では確認できない情報", set()),
}
FIELDS = {
    "equipment_name": "ATTRIBUTES",
    "equipment_code": "ATTRIBUTES",
    "equipment_type": "ATTRIBUTES",
    "active": "ATTRIBUTES",
    "registered_state": "STATE",
    "maintenance_records": "MAINTENANCE",
    "maintenance_plans": "MAINTENANCE",
    "upstream_dependencies": "UPSTREAM",
    "downstream_reachability": "DOWNSTREAM",
    "alternative_candidates": "ALTERNATIVES",
    "common_dependencies": "COMMON_DEPENDENCIES",
    "single_point_failure_candidates": "SINGLE_POINT_FAILURE",
    "economic_input": "ECONOMICS",
    "capacity_input": "CAPACITY",
    "safety_input": "SAFETY",
    "maintenance_input": "MAINTENANCE_INPUTS",
    "registered_comparison": "COMPARISON",
    "document_excerpt": "DOCUMENTS",
}

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "requested_fields": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {"type": "string", "minLength": 1, "maxLength": 100},
            "description": "質問で求められた属性・情報を表すfield名。対応fieldがない場合も、近い既存fieldに置換せず求められた属性名をそのまま表す。",
        },
        "subjects": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": [
                            "Equipment",
                            "Process",
                            "Product",
                            "ProductionOperation",
                            "InfrastructureResource",
                        ],
                    },
                    "reference": {"type": "string", "minLength": 1, "maxLength": 200},
                },
                "required": ["entity_type", "reference"],
            },
        },
        "source_spans": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
            "description": "最後の質問本文の尋ねている語句を原文のまま抽出。文字位置はコードが照合して計算するため出力しない。対象以外の属性・修飾・疑問を落とさない。",
        },
        "topics": {
            "type": "array",
            "minItems": 1,
            "maxItems": 15,
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(TOPICS)},
        },
    },
    "required": ["topics", "subjects", "requested_fields", "source_spans"],
    "description": "質問の情報種別を分類する内部処理。事実や回答文を生成しない。",
}
SELECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fact_ids": {
            "type": "array",
            "maxItems": 80,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^f[1-9][0-9]*$"},
        }
    },
    "required": ["fact_ids"],
    "description": "取得を終え、answer_factsの実在IDを選択・整理して回答する。文章・値はサーバが生成する。未取得の情報を作らない。",
}
SCOPE_PROMPT = """LineScopeの質問を情報種別へ分類しdescribe_read_requestを1回だけ呼んでください。回答文・値は生成しません。
本文に明記された対象を画面選択や過去の質問より優先します。複合質問は必要な種別を全て選びます。
登録属性はコード・名称・種類です。有効フラグactiveは通常分類から除外します。これら以外の属性はUNSUPPORTEDです。
STATEは登録状態、MAINTENANCEは保全の計画・実績、UPSTREAM等は登録関係の探索です。
登録関係の到達から、登録されていない物の場所や運転可否など別の事実は回答できません。
ECONOMICS/CAPACITY/SAFETY/MAINTENANCE_INPUTSは明示登録された入力の範囲だけです。
実運転の保証、登録対象外の情報、自由な世間話、更新や確定操作にはUNSUPPORTEDを含めてください。
不明な種別を近い種別へ無理に当てはめずUNSUPPORTEDとしてください。
subjectsには質問本文にある対象の名称またはコードをreferenceとしてそのまま抽出し、種類をentity_typeで指定します。コードや名称のない「この設備」は補足の選択だけを使用します。本文にない対象を作りません。対象がない場合は空配列にします。"""


@dataclass(frozen=True)
class ReadScope:
    topics: tuple[str, ...]
    subjects: tuple[dict, ...] = ()
    scope_issue: str | None = None
    requested_fields: tuple[str, ...] = ()
    source_spans: tuple[dict, ...] = ()
    validation_stage: str | None = None
    validation_reason: str | None = None

    def schemas(self, available):
        allowed = IDENTITY_TOOLS | set().union(*(TOPICS[t][1] for t in self.topics))
        return {name: schema for name, schema in available.items() if name in allowed}

    def labels(self):
        return [TOPICS[t][0] for t in self.topics]


def classify(llm, request, session, previous_messages=None):
    from .read_catalog import BUSINESS_FIELDS, locate_spans

    messages = [
        {
            "role": "system",
            "content": SCOPE_PROMPT
            + "\n参照可能なfieldは次だけです："
            + ", ".join(BUSINESS_FIELDS)
            + "。requested_fieldsには質問が本当に求めている属性を入れます。"
            + "一覧にその属性がなければ、既存fieldに言い換えず、求められた属性を示す別のfield名を入れてください。",
        }
    ]
    for previous in previous_messages or ():
        messages.extend(question_messages(previous))
    messages.extend(question_messages(request.message))
    reply = complete_scope(llm, messages, {PLAN_TOOL: PLAN_SCHEMA}, session)
    calls = reply.tool_calls
    if len(calls) != 1 or calls[0].name != PLAN_TOOL:
        return ReadScope((), scope_issue="UNVERIFIABLE", validation_stage="PLAN_SHAPE")
    arguments = calls[0].arguments
    if type(arguments) is not dict:
        return ReadScope((), scope_issue="UNVERIFIABLE", validation_stage="PLAN_SHAPE")
    subjects = arguments.get("subjects")
    supplied = reference_key(
        " ".join(item["content"] for item in question_messages(request.message))
    )
    if type(subjects) is not list or len(subjects) > 4:
        return ReadScope((), scope_issue="UNVERIFIABLE", validation_stage="PLAN_TARGETS")
    for subject in subjects:
        if (
            type(subject) is not dict
            or set(subject) != {"entity_type", "reference"}
            or subject["entity_type"]
            not in {
                "Equipment",
                "Process",
                "Product",
                "ProductionOperation",
                "InfrastructureResource",
            }
            or type(subject["reference"]) is not str
            or not 1 <= len(subject["reference"]) <= 200
            or not subject["reference"].strip()
            or reference_key(subject["reference"]) not in supplied
        ):
            return ReadScope((), scope_issue="UNVERIFIABLE", validation_stage="PLAN_TARGETS")
    topics = arguments.get("topics")
    if (
        set(arguments) - {"topics", "subjects", "requested_fields", "source_spans"}
        or not {"topics", "subjects", "requested_fields", "source_spans"} <= set(arguments)
        or type(topics) is not list
        or not 1 <= len(topics) <= 15
        or any(type(t) is not str or t not in TOPICS for t in topics)
        or len(topics) != len(set(topics))
    ):
        return ReadScope((), tuple(subjects), "UNVERIFIABLE", validation_stage="PLAN_SHAPE")
    requested = arguments["requested_fields"]
    if (
        type(requested) is not list
        or not 1 <= len(requested) <= 16
        or any(type(field) is not str or not 1 <= len(field) <= 100 for field in requested)
    ):
        return ReadScope((), tuple(subjects), "UNVERIFIABLE", validation_stage="PLAN_SHAPE")
    # A coarse topic is not evidence that a requested attribute exists.
    # Only catalogued fields can enable a capability; unknown fields stay unsupported.
    admitted = tuple(
        dict.fromkeys(BUSINESS_FIELDS.get(field, "UNSUPPORTED") for field in requested)
    )
    spans, problem = locate_spans(arguments["source_spans"], request.message)
    if problem:
        return ReadScope(
            admitted,
            tuple(subjects),
            "UNVERIFIABLE",
            tuple(requested),
            (),
            "SOURCE_SPANS",
            problem,
        )
    issue = None
    stage = None
    supported = [field for field in requested if field in BUSINESS_FIELDS]
    if supported:
        from .scope_check import CHECK_SCHEMA, CHECK_TOOL, check_messages, checked_verdict

        reply = complete_scope(
            llm,
            check_messages(request.message, supported, subjects),
            {CHECK_TOOL: CHECK_SCHEMA},
            session,
        )
        issue = checked_verdict(reply)
        if issue:
            stage = "COVERAGE_SHAPE" if issue == "UNVERIFIABLE" else "COVERAGE"
    return ReadScope(admitted, tuple(subjects), issue, tuple(requested), tuple(spans), stage)


def complete_scope(llm, messages, schemas, session):
    started = monotonic()
    code, output_bytes, tool_count, metrics = "OK", 0, 0, {}
    try:
        reply = llm.complete(messages, schemas=schemas, deadline=session.deadline)
        if not isinstance(reply, LLMReply):
            raise LLMError("INTERNAL_ERROR", "Invalid internal LLM reply")
        output_bytes = len(canonical_json(reply.assistant_message()).encode("utf-8"))
        tool_count, metrics = len(reply.tool_calls), dict(reply.metrics)
        session.check_deadline()
    except LLMError as error:
        code, metrics = error.code, dict(error.metrics)
        raise ToolError(error.code, error.message) from error
    except ToolError as error:
        code = error.code
        raise
    finally:
        if session.events:
            session.events.emit(
                "llm.call.completed",
                component="api",
                outcome="success" if code == "OK" else "failure",
                result_code=code,
                dependency="llm",
                request_id=session.context.request_id,
                actor_id=session.context.authenticated_user_id,
                role=session.context.role,
                duration_ms=max(0, int((monotonic() - started) * 1000)),
                llm_input_bytes=len(
                    canonical_json({"messages": messages, "schemas": schemas}).encode("utf-8")
                ),
                llm_output_bytes=output_bytes,
                llm_tool_count=tool_count,
                llm_schema_count=1,
                **metrics,
            )
    return reply
