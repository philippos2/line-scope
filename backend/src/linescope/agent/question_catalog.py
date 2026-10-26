"""Frozen demo vocabulary. No learned classification or question-specific branches."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Aspect:
    key: str
    label: str
    terms: tuple[str, ...]
    patterns: tuple[str, ...] = ()


ASPECTS = (
    Aspect(
        "registered_state",
        "登録状態",
        ("登録状態", "稼働状態"),
        (
            "{subject}は動いているか",
            "{subject}は動いてるか",
            "{subject}は止まっているか",
            "{subject}はいま死んでるか",
        ),
    ),
    Aspect(
        "downstream_reachability",
        "下流の影響範囲",
        ("下流の影響範囲",),
        (
            "{subject}停止の影響範囲はどこまでか",
            "{subject}の停止の影響範囲はどこまでか",
            "{subject}が止まるとどんな影響があるか",
        ),
    ),
    Aspect(
        "upstream_dependencies",
        "上流の依存関係",
        ("上流の依存関係",),
        ("{subject}は何に依存しているか",),
    ),
    Aspect("alternative_candidates", "構造上の代替候補", ("代替候補", "代わりになる設備")),
    Aspect(
        "maintenance_records",
        "保全実績",
        ("保全記録", "メンテナンス記録", "前回のメンテナンス日時"),
        (
            "{subject}が最後にメンテナンスされたのはいつか",
            "{subject}の前回のメンテナンス日時はいつか",
            "{subject}の前回のメンテナンス日時はいつ",
            "{subject}の前回の{term}{ending}",
        ),
    ),
    Aspect("maintenance_plans", "保全計画", ("保全計画", "メンテナンス予定")),
    Aspect("equipment_name", "登録名称", ("設備名", "登録されている名称")),
    Aspect("equipment_code", "設備コード", ("設備コード", "設備番号")),
    Aspect("equipment_type", "設備種別", ("設備の種類", "設備種別")),
)
ENDINGS = ("は", "は何", "は何か", "を教えて", "を教えてください")
DEICTIC = frozenset({"この設備", "その設備", "選択中の設備"})


def text_key(text):
    return unicodedata.normalize("NFKC", text).strip().rstrip("?？。!！ \n\t")


def matches(question):
    text = text_key(question)
    found = set()
    for aspect in ASPECTS:
        templates = ("{subject}の{term}{ending}", *aspect.patterns)
        for template in templates:
            for term in aspect.terms:
                for ending in ENDINGS:
                    pattern = re.escape(
                        template.format(subject="SUBJECT", term=term, ending=ending)
                    )
                    match = re.fullmatch(pattern.replace("SUBJECT", r"(?P<subject>.+?)"), text)
                    if match:
                        found.add((aspect.key, match["subject"]))
    return tuple(sorted(found))


def subject_expression(question):
    text = text_key(question)
    found = matches(text)
    subjects = {
        subject
        for _, subject in found
        if subject in DEICTIC or not re.search("[のはがと、,]", subject)
    }
    if len(subjects) == 1:
        return next(iter(subjects))
    return re.split("[のはが、,]", text, maxsplit=1)[0].strip()


def guidance():
    return "例えば『M-204の登録状態は？』『M-204停止の影響範囲はどこまでか？』『M-204の保全記録は？』と、一つずつ質問してください。"
