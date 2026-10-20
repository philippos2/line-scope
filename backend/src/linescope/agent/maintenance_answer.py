"""Registered maintenance facts remain distinct from generated forecasts."""


def maintenance_record_answer(observations, *, has_errors=False):
    records = [
        item.result.data for item in observations if item.tool == "search_maintenance_records"
    ]
    if (
        has_errors
        or not records
        or any(row.get("items") != [] or row.get("next_cursor") is not None for row in records)
    ):
        return None
    return (
        "今回検索した登録済みの保全記録は0件のため、最後に保全した日時は確認できません。"
        "保全作業が実施されていないことを意味するものではありません。"
    )


def maintenance_answer(observations, *, has_errors=False):
    results = [item.result.data for item in observations if item.tool == "get_maintenance_input"]
    searches = [item for item in observations if item.tool == "search_maintenance_inputs"]
    if not results:
        return (
            "登録済み対応計画・故障履歴の候補を取得しました。対象・分類・期間・出典を確認して選択してください。"
            if searches
            else None
        )
    answer = "一部の参照に失敗しています。" if has_errors else ""
    for data in results:
        record, c = data["input"], data["calculation"]
        answer += f"登録済み対応計画・故障履歴「{record['input_code']}」version {record['version']}：{c['kind']}。調達待ち {c['lead_time_hours'] if c['lead_time_hours'] is not None else '不明'} 時間、作業 {c['work_hours'] if c['work_hours'] is not None else '不明'} 時間、停止 {c['downtime_hours'] if c['downtime_hours'] is not None else '不明'} 時間。"
    return (
        answer
        + "調達待ちと作業・停止時間は別です。出典・評価期間・費用の内訳と交換費の算入条件は構造化結果を確認してください。過去損失を将来費用へ加算せず、将来故障確率・実行可能性は認定しません。次回保全の停止は予定として扱い、自動で状態変更しません。"
    )
