"""Bounded downstream prose from verified observations, without extra DB reads."""

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
