import { object, type Envelope, type JsonObject } from "../../api/client";

// Combine returned paths for display only; do not traverse or calculate losses here.
export function incidentGraph(result: Envelope): Envelope {
  const impacts = Array.isArray(result.data.impacts)
    ? result.data.impacts.filter(object)
    : [];
  if (
    !impacts.length ||
    impacts.some(
      (row) => !object(row.impact) || row.impact.graph_sync_state !== "CURRENT",
    )
  )
    throw new Error("INVALID_RESPONSE");
  const graphs = impacts.map((row) => row.impact as JsonObject);
  const unique = (values: unknown[]) => [
    ...new Map(
      values
        .filter(object)
        .map((row) => [
          String(row.entity_type) + ":" + String(row.entity_id),
          row,
        ]),
    ).values(),
  ];
  const combined = {
    graph_sync_state: "CURRENT",
    analysis_scope: "MULTIPLE_REGISTERED_IMPACTS",
    complete: graphs.every((row) => row.complete === true),
    targets: graphs.map((row) => row.target),
    reached_nodes: unique(
      graphs.flatMap((row) =>
        Array.isArray(row.reached_nodes) ? row.reached_nodes : [],
      ),
    ),
    representative_paths: graphs.flatMap((row) =>
      Array.isArray(row.representative_paths) ? row.representative_paths : [],
    ),
  };
  return {
    ...result,
    data: {
      tool_results: [
        {
          tool: "trace_downstream_impact",
          title: "選択した設備の影響をまとめて表示",
          data: combined,
        },
        ...impacts.map((row) => ({
          tool: "trace_downstream_impact",
          title: `${object(row.equipment) ? String(row.equipment.equipment_code) : "設備"}からの影響`,
          data: row.impact,
        })),
        ...impacts.map((row) => ({
          tool: "get_equipment",
          data: row.equipment,
        })),
      ],
    },
  };
}
export const lossReasons: Record<string, string> = {
  INCOMPLETE_GRAPH: "Graph探索が不完全です",
  STOPPAGE_APPLICABILITY_UNKNOWN: "停止損失の適用条件が未確認です",
  SELECT_ONE_ECONOMIC_INPUT: "設備ごとに損失の根拠を1件選んでください",
  PERIOD_MISMATCH: "根拠と評価期間が一致しません",
  PRODUCT_OUTSIDE_IMPACT: "根拠の製品が取得した影響範囲に含まれません",
  MISSING_LOSS_SCOPE: "影響製品の損失根拠が不足しています",
  CONFLICTING_SCOPE: "同じ損失範囲の根拠が一致しません",
  UNKNOWN_RATE: "損失率が不明です",
  NONINDEPENDENT_SCOPE: "独立して加算できると確認されていません",
};
export function money(value: unknown) {
  if (typeof value !== "string" || !/^\d+(\.\d+)?$/.test(value))
    return "未算出";
  const [whole, fraction] = value.split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction ? "." + fraction : ""} 円／時間`;
}
