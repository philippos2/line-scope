"""Render verified references for ordinary answers without exposing internal identifiers."""

import re
from datetime import datetime, timedelta, timezone

UUID_TEXT = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)
ENTITIES = (
    "equipment",
    "process",
    "production_operation",
    "product",
    "infrastructure_resource",
    "maintenance_record",
    "maintenance_plan",
)


def public_answer(text, observations):
    identifiers, references, timestamps = {}, {}, {}

    def visit(value):
        if isinstance(value, str) and UUID_TEXT.fullmatch(value):
            references.setdefault(value.lower(), f"取得結果の参照{len(references) + 1}")
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for prefix in ENTITIES:
                identifier = value.get(prefix + "_id")
                if isinstance(identifier, str) and UUID_TEXT.fullmatch(identifier):
                    name, code = value.get(prefix + "_name"), value.get(prefix + "_code")
                    if prefix == "production_operation":
                        code = value.get("operation_code")
                    elif prefix == "infrastructure_resource":
                        name, code = value.get("resource_name"), value.get("resource_code")
                    elif prefix == "maintenance_record":
                        code = value.get("record_code")
                    elif prefix == "maintenance_plan":
                        code = value.get("plan_code")
                    label = " · ".join(
                        item for item in (name, code) if isinstance(item, str) and item
                    )
                    if label:
                        identifiers.setdefault(identifier.lower(), set()).add(label)
            for key, item in value.items():
                if isinstance(item, str) and key.endswith(("_at", "_from", "_to")):
                    try:
                        date = datetime.fromisoformat(item.replace("Z", "+00:00"))
                        if date.utcoffset() is not None:
                            timestamps[item] = date.astimezone(
                                timezone(timedelta(hours=9))
                            ).strftime("%Y/%m/%d %H:%M:%S（日本時間）")
                    except ValueError:
                        pass
                visit(item)

    for observation in observations:
        visit(observation.result.data)

    def render_reference(match):
        key = match[0].lower()
        labels = identifiers.get(key, set())
        if len(labels) == 1:
            return next(iter(labels))
        if len(labels) > 1:
            # A UUID alone cannot distinguish conflicting typed references.
            return match[0]
        return references.get(key, match[0])

    text = UUID_TEXT.sub(render_reference, text)
    if UUID_TEXT.search(text):
        return (
            "取得情報を内部識別子を含めずに説明できませんでした。取得結果の詳細を確認してください。"
        )
    for original, rendered in timestamps.items():
        text = text.replace(original, rendered)
    return text
