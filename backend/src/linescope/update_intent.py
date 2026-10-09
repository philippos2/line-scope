"""Versioned, conservative update-command grammar over the original message.

Unsupported phrasing requires clarification. This is not semantic understanding
of arbitrary Japanese and does not resolve entities or authorize business roles.
Retrieved text and LLM-generated intent declarations are never inputs here.
"""

import re
from dataclasses import dataclass

from .agent_input import AgentInput
from .canonical import canonical_hash

RULE_VERSION = "explicit-update-command:v1"
IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_-]*"
COMMAND = r"(?:してください|して下さい|して|せよ)"
STATE = r"(?:RUNNING|STOPPED|UNDER_MAINTENANCE|UNKNOWN|稼働中|停止|保全中|不明)"
STATUS = r"(?:PLANNED|CANCELLED|計画済み|取消済み)"
TIMESTAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
# Full-message matching prevents directives inside quotations, questions,
# conditional sentences or pasted documents from becoming permission evidence.
PATTERNS = [
    ("EQUIPMENT_STATE", rf"(?:設備)?{IDENTIFIER}の状態を{STATE}に(?:更新|変更){COMMAND}"),
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
