"""Focused read planning and factual rendering for a single latest-maintenance date."""

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from ..application.reads import ToolError

PROMPT = (
    "あなたはLineScopeの参照専用アシスタントです。単一設備の直近の保全実施日時だけを尋ねる質問を扱います。"
    "日時以外も尋ねる場合はToolを呼ばず「通常調査」とだけ返してください。現在の質問の設備を優先します。"
    "質問された設備の名称またはコードを読み取り、"
    "search_equipmentを一度だけ呼んでください。名称はfilter.name、コードはfilter.equipment_codeを"
    "一方だけ指定します。原文の表記を使い、別設備を推測しません。名称の一部でも検索します。存在しないように見える名称も検索し、存在と一意性はサーバが確認します。設備への言及がない場合だけ確認を求めます。"
    "更新や権限の判断は禁止です。検索結果・保全日時は生成しません。"
)
SCHEMA = {
    "type": "object",
    "description": "Find the equipment named in the question.",
    "properties": {
        "filter": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "equipment_code": {"type": "string"}},
            "minProperties": 1,
            "maxProperties": 1,
            "additionalProperties": False,
        }
    },
    "required": ["filter"],
    "additionalProperties": False,
}


def matches(message):
    text = unicodedata.normalize("NFKC", message)
    return (
        len(text) <= 1000
        and bool(re.search(r"前回|最後|直近|最新", text))
        and bool(re.search(r"メンテナンス|保全|整備|点検", text))
        and bool(re.search(r"いつ|日時|日付|時期", text))
        and not re.search(
            r"変更|更新|削除|準備|承認|実行|無効|影響|費用|原因|安全|品質|比較|文書|および|及び|また|それと|加えて",
            text,
        )
    )


def target_selection(observations):
    searches = [item.result.data for item in observations if item.tool == "search_equipment"]
    candidates = {row["equipment_id"]: row for data in searches for row in data["items"]}
    if any(data.get("next_cursor") for data in searches) or len(candidates) > 1:
        labels = "、".join(
            f"{row['equipment_name']} · {row['equipment_code']}"
            for row in list(candidates.values())[:5]
        )
        return (
            None,
            "設備の候補を一つに特定できません。設備コードを指定してください。候補：" + labels,
        )
    if not candidates:
        return (
            None,
            "指定された名称・コードとその表記違いでは、登録設備が見つかりませんでした。設備名またはコードを確認してください。",
        )
    return next(iter(candidates.values())), None


def answer(target, observations):
    pages = [item.result.data for item in observations if item.tool == "search_maintenance_records"]
    rows = [row for page in pages for row in page["items"]]
    if not rows:
        return (
            f"{target['equipment_name']} · {target['equipment_code']}の登録済み保全記録は0件のため、"
            "前回の実施日時は確認できません。保全作業が未実施という意味ではありません。"
        )
    try:
        if any(row["equipment_id"] != target["equipment_id"] for row in rows):
            raise ValueError("Mismatched maintenance target")
        dates = [datetime.fromisoformat(row["performed_at"].replace("Z", "+00:00")) for row in rows]
        if any(date.utcoffset() is None for date in dates):
            raise ValueError("Unknown maintenance timezone")
        latest = max(dates).astimezone(timezone(timedelta(hours=9)))
    except (KeyError, TypeError, ValueError) as error:
        raise ToolError("INTERNAL_ERROR", "Invalid registered maintenance date") from error
    return (
        f"{target['equipment_name']} · {target['equipment_code']}について取得した登録済み保全記録では、"
        f"直近の実施日時は{latest:%Y/%m/%d %H:%M:%S}（日本時間）です。"
    )
