"""Explain one current state without inventing a failure cause."""


def state_answer(observations, *, has_errors=False):
    if any(
        item.tool not in {"search_equipment", "get_equipment", "get_equipment_state"}
        for item in observations
    ):
        return None
    rows = [item.result.data for item in observations if item.tool == "get_equipment_state"]
    if len(rows) != 1:
        return None
    row = rows[0]
    if (
        row.get("state_code") not in {"RUNNING", "STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"}
        or type(row.get("version")) is not int
    ):
        return None
    return (
        ("一部の参照に失敗しています。" if has_errors else "")
        + f"対象設備の登録上の現在状態は{row['state_code']}、version {row['version']}です。故障原因・安全性・将来状態はこの状態情報から判断できません。観測時刻と出典は構造化結果を確認してください。"
    )
