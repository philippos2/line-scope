"""Safety text from verified declarations, not model-generated permissions."""


def safety_answer(observations, *, has_errors=False):
    results = [item.result.data for item in observations if item.tool == "get_safety_input"]
    searches = [item.result.data for item in observations if item.tool == "search_safety_inputs"]
    if not results:
        return (
            "登録済み安全入力の候補を取得しました。対象・期間・出典を確認して入力を選択してください。安全判定は未取得です。"
            if searches
            else None
        )
    if len(results) != 1:
        return "複数の安全入力を取得しました。記録ごとに出典・期間・条件を確認してください。設備全体の安全許可として合算・認定していません。"
    data = results[0]
    if data.get("source") != "REGISTERED_INPUT":
        return None
    record, result = data["input"], data["calculation"]
    verdict = {
        "STOP_REQUIRED": "停止必須。継続案を候補から除外します。",
        "CONDITIONAL": "登録された条件の範囲で条件付き継続可とされています。",
        "UNKNOWN": "安全判定は不明です。継続可能とは認定しません。",
    }[result["status"]]
    answer = f"登録済み安全入力「{record['input_code']}」version {record['version']}：{verdict}適用期間・観測・安全基準・出典・継続条件は構造化結果を確認してください。単一記録の評価であり、設備全体の安全や運転許可を認定しません。残存リスクは不明です。"
    return ("一部の参照に失敗しています。" if has_errors else "") + answer
