"""Capacity prose from verified server results; never infer operational feasibility."""


def capacity_answer(observations, *, has_errors=False):
    results = [item.result.data for item in observations if item.tool == "get_capacity_input"]
    searches = [item.result.data for item in observations if item.tool == "search_capacity_inputs"]
    if not results:
        if not searches:
            return None
        return f"登録済み能力入力の候補を{len(searches[-1]['items'])}件取得しました。対象製品・単位・期間を確認して入力を選択してください。能力・復旧期限の計算結果は未取得です。"
    if len(results) != 1:
        return "複数の能力入力を取得しました。製品・単位・期間ごとに構造化結果を確認してください。合算や完全代替の判定はしていません。"
    data = results[0]
    if data.get("source") != "REGISTERED_INPUT":
        return None
    record, result = data["input"], data["calculation"]
    status = {
        "SUFFICIENT": "能力面で充足",
        "INSUFFICIENT": "能力不足",
        "INCOMPATIBLE": "製品非互換",
        "UNKNOWN": "能力判定不明",
    }[result["capacity_status"]]

    def shown(value):
        return value if value is not None else "不明"

    answer = (
        f"登録済み能力入力「{record['input_code']}」version {record['version']}：{status}。"
        f"必要{shown(result['required_rate'])}、利用可能{shown(result['available_rate'])}、不足{shown(result['shortage_rate'])} {result['quantity_unit']}/hour。"
        + (
            f"条件付き許容停止時間{result['permissible_downtime_hours']}時間、復旧期限{result['recovery_deadline']}。"
            if result["recovery_status"] == "CONDITIONAL"
            else "復旧期限は不明です。"
        )
        + "安全・品質・実稼働・完全代替は未評価です。製品・期間・出典・計算前提は構造化結果を確認してください。"
    )
    return ("一部の参照に失敗しています。" if has_errors else "") + answer
