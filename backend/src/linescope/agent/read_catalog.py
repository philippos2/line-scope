"""Finite business capability definitions and whole-question literal grammar.

No equipment, question examples, colloquial exception list or model confidence
is used as a routing rule. Unparsed text never grants a business read.
"""

import re
from dataclasses import dataclass

from .equipment_reference import question_messages, selected_reference
from .read_scope import FIELDS, ReadScope
from .scope_check import FIELD_MEANINGS

CATALOG_VERSION = "h6-2"
TECHNICAL_FIELDS = frozenset({"active"})
BUSINESS_FIELDS = {key: value for key, value in FIELDS.items() if key not in TECHNICAL_FIELDS}
# Literal vocabulary belongs to capability definitions, not to question routes.
TERMS = {
    "equipment_name": ("設備名", "設備の名称"),
    "equipment_code": ("設備コード", "設備番号", "機番"),
    "equipment_type": ("設備種別", "設備の種類"),
    "registered_state": ("登録状態", "登録運用状態", "登録上の状態"),
    "maintenance_records": ("保全記録", "メンテナンス記録", "保全実績"),
    "maintenance_plans": ("保全計画", "メンテナンス計画"),
    "upstream_dependencies": ("上流の依存関係", "上流依存関係"),
    "downstream_reachability": ("下流への影響範囲", "下流の依存関係"),
    "alternative_candidates": ("構造上の代替候補", "代替候補"),
    "common_dependencies": ("共通の依存先", "共通依存先"),
    "single_point_failure_candidates": ("単一障害点の候補",),
    "economic_input": ("経済入力", "算定データ"),
    "capacity_input": ("能力入力", "能力データ"),
    "safety_input": ("安全入力", "安全条件の入力"),
    "maintenance_input": ("対応計画の入力", "故障履歴の入力"),
    "registered_comparison": ("正式入力の比較",),
    "document_excerpt": ("関連文書",),
}
REGISTERED_VALUES = {
    "稼働中": "RUNNING",
    "停止中": "STOPPED",
    "保全中": "UNDER_MAINTENANCE",
    "稼働しています": "RUNNING",
    "停止しています": "STOPPED",
    "保全作業中": "UNDER_MAINTENANCE",
}
END = r"(?:は|は何|は何か|は何ですか|を教えて|を教えてください|を見せて|を見せてください)"
PUNCT = r"[?？。]*"
# Seven grammar shapes. Terms are bound separately from the shared syntax.
SHAPES = {
    "definition": r"{term}(?:とは|とは何|とは何か|って何|って何ですか){punct}",
    "value": r"(?P<subject>.+?)の(?:(?:いま|今|現在)の)?{term}{end}{punct}",
    "boolean": r"(?P<subject>.+?)(?:は|、|,)(?:いま|今|現在)?{term}(?:か|ですか){punct}",
    "relation": r"(?P<subject>.+?)の{term}{end}{punct}",
    "record_list": r"(?P<subject>.+?)の{term}{end}{punct}",
    "record_event_time": r"(?P<subject>.+?)が(?:最後|前回)に{term}されたのはいつ(?:か|ですか)?{punct}",
    "record_time": r"(?P<subject>.+?)の(?:前回|最後)の{term}(?:日時|実施日時|実施日)(?:はいつ|はいつか|を教えて){punct}",
}
RELATION_FIELDS = frozenset(
    {
        "upstream_dependencies",
        "downstream_reachability",
        "alternative_candidates",
        "common_dependencies",
        "single_point_failure_candidates",
    }
)
RECORD_FIELDS = frozenset({"maintenance_records", "maintenance_plans"})
RECORD_TERMS = {
    "maintenance_records": ("保全", "メンテナンス"),
    "maintenance_plans": ("保全計画", "メンテナンス計画"),
}

# Only completed-record capabilities declare an event and its registered time.
RECORD_EVENTS = {
    "maintenance_records": {
        "activities": RECORD_TERMS["maintenance_records"],
        "time_field": "performed_at",
    }
}


@dataclass(frozen=True)
class LiteralRead:
    field: str
    kind: str
    subject: str | None = None
    predicate_value: str | None = None

    def scope(self):
        return ReadScope(
            (BUSINESS_FIELDS[self.field],),
            ({"entity_type": "Equipment", "reference": self.subject},),
            requested_fields=(self.field,),
        )


def literal_reads(message):
    text = question_messages(message)[-1]["content"].strip()
    matches = set()
    for field, terms in TERMS.items():
        shape = (
            "record_list"
            if field in RECORD_FIELDS
            else "relation"
            if field in RELATION_FIELDS
            else "value"
        )
        for kind, vocabulary in (
            ("definition", terms),
            (shape, terms),
            ("record_time", RECORD_TERMS.get(field, ())),
            ("record_event_time", RECORD_EVENTS.get(field, {}).get("activities", ())),
        ):
            for term in vocabulary:
                pattern = SHAPES[kind].format(term=re.escape(term), end=END, punct=PUNCT)
                match = re.fullmatch(pattern, text)
                if match:
                    subject = match.groupdict().get("subject")
                    if subject is not None:
                        subject = selected_reference(message, subject)
                    matches.add(LiteralRead(field, kind, subject))
    for term, value in REGISTERED_VALUES.items():
        match = re.fullmatch(SHAPES["boolean"].format(term=re.escape(term), punct=PUNCT), text)
        if match:
            matches.add(
                LiteralRead(
                    "registered_state",
                    "boolean",
                    selected_reference(message, match["subject"]),
                    value,
                )
            )
    return tuple(
        sorted(
            matches,
            key=lambda item: (
                item.field,
                item.kind,
                item.subject or "",
                item.predicate_value or "",
            ),
        )
    )


def literal_read(message):
    matches = literal_reads(message)
    return matches[0] if len(matches) == 1 else None


def unbound_attribute(scope, message):
    """Bind an explicit nominal attribute to the proposed capability.

    Inspect explicit noun roles against identified subjects and catalog definitions;
    this does not accept arbitrary-language reads. Colloquial predicates without
    an explicit nominal attribute remain on the interpretation/clarification path.
    An explicit unbound attribute cannot be replaced by a nearby capability,
    even if both model calls agree. No negative vocabulary is consulted.
    """
    if not scope.subjects or any(s["entity_type"] != "Equipment" for s in scope.subjects):
        return None
    from .equipment_reference import reference_key

    references = [
        re.escape(reference_key(selected_reference(message, subject["reference"])))
        for subject in scope.subjects
    ]
    # Subjects come from independently looked-up references, never a greedy noun split.
    subject = "(?:" + "|".join(references) + ")"
    subjects = subject + r"(?:(?:と|、|,|及び)" + subject + r")*"
    text = reference_key(question_messages(message)[-1]["content"]).strip()
    event = re.fullmatch(
        SHAPES["record_event_time"]
        .format(term=r"(?P<activity>.+?)", punct=PUNCT)
        .replace(r"(?P<subject>.+?)", subjects),
        text,
    )
    if event:
        bound_events = {
            field
            for field, event_definition in RECORD_EVENTS.items()
            if any(
                reference_key(term) == event["activity"] for term in event_definition["activities"]
            )
        }
        if not scope.requested_fields or not set(scope.requested_fields) <= bound_events:
            return event["activity"]
        return None
    # Attribute inspection does not grant a read or add an accepted literal shape.
    nominal = re.fullmatch(
        subjects
        + r"の(?P<attribute>.+?)(?:"
        + END
        + r"|は(?:いつ|どこ|同じ)(?:まで|です|か|ですか)*|はいつまでか)"
        + PUNCT,
        text,
    )
    membership = re.fullmatch(
        subjects + r"は(?:まだ|現在|今)?(?P<attribute>.+?)(?:内|外)(?:か|ですか)" + PUNCT,
        text,
    )
    match = nominal or membership
    if not match:
        return None
    attribute = match["attribute"]
    bound = {
        field
        for field, terms in TERMS.items()
        if any(
            re.fullmatch(
                r"(?:(?:前回|最後|最新|登録済み)の)?" + re.escape(reference_key(term)), attribute
            )
            for term in terms
        )
    }
    if not bound or not scope.requested_fields or not set(scope.requested_fields) <= bound:
        return attribute
    return None


def locate_spans(spans, message):
    """Validate verbatim extraction and calculate positions without model arithmetic.

    Repeated phrases are not assigned an arbitrary first occurrence. This checks
    provenance only; semantic coverage is still checked separately.
    """
    text = question_messages(message)[-1]["content"]
    if type(spans) is not list or not 1 <= len(spans) <= 16:
        return (), "SPAN_FORMAT"
    located = []
    for span in spans:
        if type(span) is not dict or set(span) != {"text"}:
            return (), "SPAN_FORMAT"
        phrase = span["text"]
        if type(phrase) is not str or not phrase:
            return (), "SPAN_FORMAT"
        start = text.find(phrase)
        if start < 0:
            return (), "SPAN_TEXT_ABSENT"
        if text.find(phrase, start + 1) >= 0:
            return (), "SPAN_AMBIGUOUS"
        located.append({"text": phrase, "start": start, "end": start + len(phrase)})
    return tuple(located), None


def definitions_answer(field):
    text = FIELD_MEANINGS[field]
    return {
        "version": 1,
        "read_outcome": "AUTO",
        "facts": [],
        "unavailable": [],
        "scope": [],
        "definitions": [
            {
                "catalog_key": field,
                "text": text,
                "catalog_version": CATALOG_VERSION,
                "source": "CAPABILITY_CATALOG",
            }
        ],
    }


# Required subject cardinality is a capability contract, not an intent keyword rule.
SUBJECT_COUNTS = {field: (1, 4) for field in BUSINESS_FIELDS}
SUBJECT_COUNTS["document_excerpt"] = (0, 4)
SUBJECT_COUNTS["common_dependencies"] = (2, 4)


def subjects_sufficient(scope):
    return all(
        SUBJECT_COUNTS.get(field, (1, 4))[0]
        <= len(scope.subjects)
        <= SUBJECT_COUNTS.get(field, (1, 4))[1]
        for field in scope.requested_fields
    )
