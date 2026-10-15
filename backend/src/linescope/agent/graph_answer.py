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


def downstream_answer(observations, *, has_errors=False):
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
    answer += "実際の停止影響・能力・安全性・経済影響は未評価です。詳細経路と根拠は構造化結果をご確認ください。"
    if has_errors:
        answer += "一部の参照は失敗しています。エラー情報をご確認ください。"
    return answer


def dependency_answer(observations, *, has_errors=False):
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
    answer += "実際の停止影響・能力・安全性・経済影響は未評価です。詳細経路と根拠は構造化結果をご確認ください。"
    if has_errors:
        answer += "一部の参照は失敗しています。エラー情報をご確認ください。"
    return answer
