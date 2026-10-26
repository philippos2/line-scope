"""Bounded reachability prose from verified observations, without extra DB reads."""

from collections import Counter

from .graph_model_view import GRAPH_TOOLS

TYPE_LABELS = {
    "Equipment": "設備",
    "Process": "工程",
    "ProductionOperation": "生産作業",
    "Product": "製品",
    "InfrastructureResource": "インフラ",
}


def downstream_answer(observations, *, has_errors=False, include_detail_link=True):
    """Render only a single supported analysis; preserve all raw data/Evidence."""
    graphs = [item for item in observations if item.tool in GRAPH_TOOLS]
    if len(graphs) != 1 or graphs[0].tool != "trace_downstream_impact":
        return None
    data = graphs[0].result.data
    if (
        data.get("analysis_scope") != "DEPENDENCY_REACHABILITY"
        or data.get("graph_sync_state") != "CURRENT"
        or type(data.get("complete")) is not bool
        or data.get("not_evaluated") != ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"]
        or not all(
            isinstance(data.get(key), list)
            for key in ("reached_nodes", "direct_nodes", "indirect_nodes")
        )
    ):
        return None

    def nodes(key):
        return {(item["entity_type"], item["entity_id"]) for item in data[key]}

    reached, direct, indirect = (
        nodes(key) for key in ("reached_nodes", "direct_nodes", "indirect_nodes")
    )
    if direct & indirect or direct | indirect != reached:
        return None

    def describe(group):
        counts = Counter(kind for kind, _ in group)
        types = "、".join(
            f"{label}{counts[kind]}件" for kind, label in TYPE_LABELS.items() if counts[kind]
        )
        return f"{len(group)}件" + (f"（{types}）" if types else "")

    answer = (
        f"指定対象の下流に{len(reached)}件の依存到達候補を確認しました。"
        f"直接{describe(direct)}、間接{describe(indirect)}。"
    )
    answer += (
        "この探索範囲は確認済みです。"
        if data["complete"]
        else "探索は不完全で、未取得の対象・経路があり得ます。影響なしとは判断できません。"
    )
    answer += "実際の停止影響・能力・安全性・経済影響は未評価です。"
    if include_detail_link:
        answer += "詳細経路と根拠は構造化結果をご確認ください。"
    if has_errors:
        answer += "一部の参照は失敗しています。エラー情報をご確認ください。"
    return answer


def dependency_answer(observations, *, has_errors=False, include_detail_link=True):
    """Summarize one upstream/common search without implying cause or impact."""
    graphs = [item for item in observations if item.tool in GRAPH_TOOLS]
    if len(graphs) != 1:
        return None
    item = graphs[0]
    if item.tool not in {"trace_upstream_dependencies", "find_common_dependencies"}:
        return None
    data = item.result.data
    if (
        data.get("analysis_scope") != "DEPENDENCY_REACHABILITY"
        or data.get("graph_sync_state") != "CURRENT"
        or type(data.get("complete")) is not bool
        or data.get("not_evaluated") != ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"]
    ):
        return None

    def nodes(key):
        values = data.get(key)
        if not isinstance(values, list) or any(
            not isinstance(value, dict)
            or value.get("entity_type") not in TYPE_LABELS
            or not isinstance(value.get("entity_id"), str)
            or not value["entity_id"]
            for value in values
        ):
            return None
        result = {(value["entity_type"], value["entity_id"]) for value in values}
        return result if len(result) == len(values) else None

    if item.tool == "trace_upstream_dependencies":
        reached, direct, indirect = (
            nodes(key) for key in ("reached_nodes", "direct_nodes", "indirect_nodes")
        )
        if any(group is None for group in (reached, direct, indirect)):
            return None
        if direct & indirect or direct | indirect != reached:
            return None
        counts = Counter(kind for kind, _ in reached)
        types = "、".join(
            f"{label}{counts[kind]}件" for kind, label in TYPE_LABELS.items() if counts[kind]
        )
        answer = (
            f"指定対象の上流に{len(reached)}件の依存到達要素を確認しました。"
            f"1段上流{len(direct)}件、2段以上の上流{len(indirect)}件。"
        )
        if types:
            answer += types + "。"
        unavailable = "上流依存なし"
    else:
        targets, candidates = nodes("targets"), nodes("common_candidates")
        if targets is None or len(targets) < 2 or candidates is None:
            return None
        answer = f"指定{len(targets)}対象に共通する上流依存候補を{len(candidates)}件確認しました。"
        answer += "共通依存候補は故障原因やSPOFの確定判定ではありません。"
        unavailable = "共通依存なし"
    answer += (
        "この探索範囲は確認済みです。"
        if data["complete"]
        else f"探索は不完全で、未取得の対象・経路があり得ます。{unavailable}とは判断できません。"
    )
    answer += "実際の停止影響・能力・安全性・経済影響は未評価です。"
    if include_detail_link:
        answer += "詳細経路と根拠は構造化結果をご確認ください。"
    if has_errors:
        answer += "一部の参照は失敗しています。エラー情報をご確認ください。"
    return answer


def fulfillment_answer(observations, *, has_errors=False):
    """Describe server structural verdicts; never derive a new business verdict."""
    graphs = [item for item in observations if item.tool in GRAPH_TOOLS]
    if len(graphs) != 1 or graphs[0].tool not in {
        "find_alternative_paths",
        "find_single_point_failure_candidates",
    }:
        return None
    item = graphs[0]
    data = item.result.data
    if (
        data.get("analysis_scope") != "DEPENDENCY_FULFILLMENT"
        or data.get("graph_sync_state") != "CURRENT"
        or type(data.get("complete")) is not bool
        or data.get("determination") not in {"DETERMINATE", "INDETERMINATE"}
        or data.get("analysis_mode") not in {"CURRENT", "EXPLICIT_HISTORICAL"}
        or data.get("not_evaluated") != ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"]
    ):
        return None

    def counts(rows, key, labels):
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or row.get(key) not in labels for row in rows
        ):
            return None
        values = Counter(row[key] for row in rows)
        return "、".join(f"{label}{values[value]}件" for value, label in labels.items())

    if item.tool == "find_alternative_paths":
        targets = data.get("target_results")
        if (
            not isinstance(targets, list)
            or not targets
            or any(
                not isinstance(row, dict) or not isinstance(row.get("after"), dict)
                for row in targets
            )
        ):
            return None
        verdicts = counts(
            [row["after"] for row in targets],
            "determination",
            {"ESTABLISHED": "成立", "NOT_ESTABLISHED": "不成立", "INDETERMINATE": "判定不明"},
        )
        replacements = counts(
            data.get("alternatives"),
            "availability",
            {"AVAILABLE": "利用可能", "UNAVAILABLE": "利用不可", "UNKNOWN": "不明"},
        )
        if verdicts is None or replacements is None:
            return None
        answer = f"指定対象の仮想除外後の構造判定は{verdicts}。一段代替の構造上の利用可能性は{replacements}。"
    else:
        verdicts = counts(
            data.get("findings"),
            "determination",
            {"CANDIDATE": "候補", "NOT_CANDIDATE": "非候補", "INDETERMINATE": "判定不明"},
        )
        if verdicts is None:
            return None
        answer = f"対象と候補の組ごとに、一要素ずつ仮想除外した構造上のSPOF判定は{verdicts}。"
        answer += "この対象・候補範囲だけの判定で、故障原因の確定ではありません。"
        if not data["findings"]:
            answer += "評価した組はなく、SPOFなしとは判断できません。"
    answer += (
        "探索は完全です。"
        if data["complete"]
        else "探索は不完全で、未取得の対象・経路があり得ます。"
    )
    if data["determination"] == "INDETERMINATE":
        answer += "全体判定は未確定です。"
    if data["analysis_mode"] == "EXPLICIT_HISTORICAL":
        answer += "現在の登録関係を指定時点で評価した結果で、当時の状態の復元ではありません。"
    answer += "実際の停止影響・能力・安全性・経済影響は未評価です。対象別の判定と根拠は構造化結果をご確認ください。"
    if has_errors:
        answer += "一部の参照は失敗しています。エラー情報をご確認ください。"
    return answer
