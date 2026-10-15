"""Economic prose from a single verified registered input, never model arithmetic."""


def economic_answer(observations, *, has_errors=False):
    results = [item.result.data for item in observations if item.tool == "get_economic_input"]
    searches = [item.result.data for item in observations if item.tool == "search_economic_inputs"]
    if not results:
        if not searches:
            return None
        candidates = searches[-1]
        return (
            f"登録済み経済入力の候補を{len(candidates['items'])}件取得しました。"
            + ("検索の続きは未取得です。" if candidates["next_cursor"] is not None else "")
            + "対象・比較期間を確認して入力を選択してください。費用の計算結果はまだ取得していません。未登録値を仮値で補完しません。"
        )
    if len(results) != 1:
        return "複数の経済入力を取得しました。対象・期間・versionが異なる見積を合算せず、構造化結果を個別に確認してください。能力・安全性・案の優劣は未評価です。"
    if results[0].get("source") != "REGISTERED_INPUT":
        return None
    data = results[0]
    record, calculation = data["input"], data["calculation"]
    labels = {"REPAIR": "修理", "REPLACE": "交換", "CONTINUE": "継続"}
    costs = []
    for option in calculation["options"]:
        total = option["total_jpy"]
        costs.append(
            labels[option["option"]]
            + (
                f"見積総額{total}円"
                if total is not None
                else f"総額不明（既知小計{option['known_subtotal_jpy']}円）"
            )
        )
    answer = (
        f"登録済み経済入力「{record['input_code']}」version {record['version']}の明示期間・稼働時間に基づく計算です。"
        + "、".join(costs)
        + "。安全性・能力・案の優劣は未評価です。期間・出典は構造化結果を確認してください。"
    )
    return ("一部の参照に失敗しています。" if has_errors else "") + answer
