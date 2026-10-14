"""Versioned, conservative update-command grammar over the original message.

Unsupported phrasing requires clarification. This is not semantic understanding
of arbitrary Japanese and does not resolve entities or authorize business roles.
Retrieved text and LLM-generated intent declarations are never inputs here.
"""

import re
from dataclasses import dataclass

from ..domain.canonical import canonical_hash
from .agent_input import AgentInput

RULE_VERSION = "explicit-update-command:v4"
IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_-]*"
COMMAND = r"(?:してください|して下さい|して|せよ)"
STATE = r"(?:RUNNING|STOPPED|UNDER_MAINTENANCE|UNKNOWN|稼働中|停止|保全中|不明)"
STATUS = r"(?:PLANNED|CANCELLED|計画済み|取消済み)"
TIMESTAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
# Full-message matching prevents directives inside quotations, questions,
# conditional sentences or pasted documents from becoming permission evidence.
EQUIPMENT_STATE_PATTERN = (
    rf"(?:設備)?(?P<equipment_code>{IDENTIFIER})の(?:現在)?状態を"
    rf"(?P<state>{STATE})に(?:更新|変更)(?:{COMMAND}|する準備を(?:作って|作成{COMMAND}))"
)
MAINTENANCE_PLAN_CREATE_PATTERN = (
    rf"(?:設備)?(?P<equipment_code>{IDENTIFIER})の保全予定(?P<code>{IDENTIFIER})を"
    rf"開始(?P<start>{TIMESTAMP})、終了(?P<end>{TIMESTAMP})、状態(?P<status>{STATUS})で"
    rf"(?:登録|作成){COMMAND}"
)
MAINTENANCE_RECORD_CREATE_PATTERN = (
    rf"(?:設備)?(?P<equipment_code>{IDENTIFIER})の保全実績(?P<code>{IDENTIFIER})を"
    rf"実施(?P<performed_at>{TIMESTAMP})、結果「(?P<result>[^「」\r\n]+)」"
    rf"(?:、保全予定(?P<plan_code>{IDENTIFIER})に紐づけて|で)(?:登録|作成){COMMAND}"
)
PRODUCTION_ASSIGNMENT_PATTERN = (
    rf"生産作業(?P<code>{IDENTIFIER})の設備割当を"
    rf"開始(?P<start>{TIMESTAMP})、終了(?P<end>{TIMESTAMP}|無期限)、"
    rf"設備\[(?P<equipment>(?:{IDENTIFIER}(?:,{IDENTIFIER})*)?)\]に置換{COMMAND}"
)
PATTERNS = [
    ("EQUIPMENT_STATE", EQUIPMENT_STATE_PATTERN),
    ("MAINTENANCE", MAINTENANCE_PLAN_CREATE_PATTERN),
    ("MAINTENANCE", MAINTENANCE_RECORD_CREATE_PATTERN),
    ("PRODUCTION_OPERATION", PRODUCTION_ASSIGNMENT_PATTERN),
    ("MAINTENANCE", rf"(?:設備)?{IDENTIFIER}の(?:保全予定|保全実績)を(?:登録|作成){COMMAND}"),
    (
        "MAINTENANCE",
        rf"保全予定{IDENTIFIER}の(?:開始時刻|終了時刻)を{TIMESTAMP}に(?:更新|変更){COMMAND}",
    ),
    ("MAINTENANCE", rf"保全予定{IDENTIFIER}の状態を{STATUS}に(?:更新|変更){COMMAND}"),
    (
        "PRODUCTION_OPERATION",
        rf"生産作業{IDENTIFIER}の(?:予定開始時刻|予定終了時刻)を{TIMESTAMP}に(?:更新|変更){COMMAND}",
    ),
    ("PRODUCTION_OPERATION", rf"生産作業{IDENTIFIER}の予定状態を{STATUS}に(?:更新|変更){COMMAND}"),
    ("DEPENDENCY", rf"依存関係{IDENTIFIER}を無効化{COMMAND}"),
]


@dataclass(frozen=True)
class UpdateIntent:
    rule_version: str
    confirmed: bool
    category: str | None
    source_message_hash: str
    evidence_start: int | None
    evidence_end: int | None


@dataclass(frozen=True)
class EquipmentStateCommand:
    intent: UpdateIntent
    equipment_code: str
    state_code: str


def equipment_state_command(request):
    """Extract values only from the same original-message permission evidence."""
    intent = assess_update_intent(request)
    if not intent.confirmed or intent.category != "EQUIPMENT_STATE":
        return None
    match = re.fullmatch(
        EQUIPMENT_STATE_PATTERN, request.message[intent.evidence_start : intent.evidence_end]
    )
    states = {
        "稼働中": "RUNNING",
        "停止": "STOPPED",
        "保全中": "UNDER_MAINTENANCE",
        "不明": "UNKNOWN",
    }
    state = match["state"]
    return EquipmentStateCommand(intent, match["equipment_code"], states.get(state, state))


def assess_update_intent(request):
    if not isinstance(request, AgentInput):
        raise ValueError("A validated original Agent request is required")
    message = request.message
    normalized = message.strip()
    # A single final Japanese period is allowed, while preserving source offsets.
    if normalized.endswith("。"):
        normalized = normalized[:-1]
    start = len(message) - len(message.lstrip())
    digest = canonical_hash(message)
    for category, pattern in PATTERNS:
        if re.fullmatch(pattern, normalized):
            return UpdateIntent(
                RULE_VERSION, True, category, digest, start, start + len(normalized)
            )
    return UpdateIntent(RULE_VERSION, False, None, digest, None, None)


@dataclass(frozen=True)
class MaintenancePlanCommand:
    intent: UpdateIntent
    plan_code: str
    patch: dict


@dataclass(frozen=True)
class MaintenanceCreateCommand:
    intent: UpdateIntent
    equipment_code: str
    tool: str
    values: dict
    plan_code: str | None = None


def maintenance_create_command(request):
    """All CREATE values originate in the full explicit original request.

    This bounded grammar is an admission mechanism, not a new business rule or
    general Japanese understanding. Tool/Prepare still validate all invariants.
    """
    intent = assess_update_intent(request)
    if not intent.confirmed or intent.category != "MAINTENANCE":
        return None
    message = request.message[intent.evidence_start : intent.evidence_end]
    plan = re.fullmatch(MAINTENANCE_PLAN_CREATE_PATTERN, message)
    if plan:
        statuses = {"計画済み": "PLANNED", "取消済み": "CANCELLED"}
        return MaintenanceCreateCommand(
            intent,
            plan["equipment_code"],
            "prepare_maintenance_plan_create",
            {
                "plan_code": plan["code"],
                "planned_start": plan["start"],
                "planned_end": plan["end"],
                "plan_status": statuses.get(plan["status"], plan["status"]),
            },
        )
    record = re.fullmatch(MAINTENANCE_RECORD_CREATE_PATTERN, message)
    if record:
        return MaintenanceCreateCommand(
            intent,
            record["equipment_code"],
            "prepare_maintenance_record_create",
            {
                "record_code": record["code"],
                "performed_at": record["performed_at"],
                "result": record["result"],
            },
            record["plan_code"],
        )
    return None


def maintenance_plan_command(request):
    """Extract the existing explicit plan UPDATE grammar, never generated text."""
    intent = assess_update_intent(request)
    if not intent.confirmed or intent.category != "MAINTENANCE":
        return None
    message = request.message[intent.evidence_start : intent.evidence_end]
    status = re.fullmatch(
        rf"保全予定(?P<code>{IDENTIFIER})の状態を(?P<value>{STATUS})に(?:更新|変更){COMMAND}",
        message,
    )
    if status:
        values = {"計画済み": "PLANNED", "取消済み": "CANCELLED"}
        return MaintenancePlanCommand(
            intent, status["code"], {"plan_status": values.get(status["value"], status["value"])}
        )
    timestamp = re.fullmatch(
        rf"保全予定(?P<code>{IDENTIFIER})の(?P<field>開始時刻|終了時刻)を(?P<value>{TIMESTAMP})に(?:更新|変更){COMMAND}",
        message,
    )
    if timestamp:
        field = "planned_start" if timestamp["field"] == "開始時刻" else "planned_end"
        return MaintenancePlanCommand(intent, timestamp["code"], {field: timestamp["value"]})
    return None


@dataclass(frozen=True)
class ProductionScheduleCommand:
    intent: UpdateIntent
    operation_code: str
    patch: dict


@dataclass(frozen=True)
class ProductionAssignmentCommand:
    intent: UpdateIntent
    operation_code: str
    effective_from: str
    effective_to: str | None
    equipment_codes: tuple[str, ...]


def production_assignment_command(request):
    """Explicit full replacement; [] means empty set and 無期限 means NULL."""
    intent = assess_update_intent(request)
    if not intent.confirmed or intent.category != "PRODUCTION_OPERATION":
        return None
    match = re.fullmatch(
        PRODUCTION_ASSIGNMENT_PATTERN, request.message[intent.evidence_start : intent.evidence_end]
    )
    if match is None:
        return None
    return ProductionAssignmentCommand(
        intent,
        match["code"],
        match["start"],
        None if match["end"] == "無期限" else match["end"],
        tuple(match["equipment"].split(",")) if match["equipment"] else (),
    )


def production_schedule_command(request):
    """Extract only existing schedule grammar from the original permission evidence."""
    intent = assess_update_intent(request)
    if not intent.confirmed or intent.category != "PRODUCTION_OPERATION":
        return None
    message = request.message[intent.evidence_start : intent.evidence_end]
    status = re.fullmatch(
        rf"生産作業(?P<code>{IDENTIFIER})の予定状態を(?P<value>{STATUS})に(?:更新|変更){COMMAND}",
        message,
    )
    if status:
        values = {"計画済み": "PLANNED", "取消済み": "CANCELLED"}
        return ProductionScheduleCommand(
            intent, status["code"], {"planned_status": values.get(status["value"], status["value"])}
        )
    timestamp = re.fullmatch(
        rf"生産作業(?P<code>{IDENTIFIER})の(?P<field>予定開始時刻|予定終了時刻)を(?P<value>{TIMESTAMP})に(?:更新|変更){COMMAND}",
        message,
    )
    if timestamp:
        field = "planned_start" if timestamp["field"] == "予定開始時刻" else "planned_end"
        return ProductionScheduleCommand(intent, timestamp["code"], {field: timestamp["value"]})
    return None
