import {
  ApiError,
  object,
  request,
  type Envelope,
  type JsonObject,
} from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { node, nodeKey, type NodeRef } from "../graph/model";

export type ReadState = { value?: Envelope; error?: string; loading?: boolean };
export const rows = (v: unknown): JsonObject[] =>
  Array.isArray(v) ? v.filter(object) : [];
export const registeredState = (v: unknown) =>
  ({
    RUNNING: "稼働中",
    STOPPED: "停止中",
    UNDER_MAINTENANCE: "保全中",
    UNKNOWN: "不明",
  })[String(v)] ?? "確認中";
export function errorCode(e: unknown) {
  return e instanceof ApiError ? e.code : "INVALID_RESPONSE";
}
export function explanation(code: string) {
  return (
    (
      {
        AUTHENTICATION_REQUIRED: "接続が切れました。接続し直してください。",
        AUTHORIZATION_DENIED: "この情報を表示する権限がありません。",
        GRAPH_NOT_CURRENT: "関係データの更新待ちです。",
        GRAPH_REBUILDING: "関係データを再構築中です。",
        CONNECTION_FAILED: "接続できませんでした。",
        DEPENDENCY_UNAVAILABLE: "情報の取得先を利用できません。",
      } as Record<string, string>
    )[code] ?? "情報を取得できませんでした。"
  );
}
export async function direct(
  tool: string,
  args: JsonObject,
  signal: AbortSignal,
) {
  return request(
    "",
    "/agent",
    { message: `関係分析 ${JSON.stringify({ tool, arguments: args })}` },
    signal,
  );
}
export function toolData(result?: Envelope): JsonObject {
  const row = rows(result?.data.tool_results)[0];
  return object(row?.data) ? row.data : {};
}
export function generation(result?: Envelope) {
  return (
    result?.evidence.graph_generation ??
    (object(result?.evidence.impact)
      ? result.evidence.impact.graph_generation
      : undefined) ??
    rows(result?.evidence.tool_results)[0]?.graph_generation
  );
}
export function candidates(result?: Envelope): NodeRef[] {
  return rows(toolData(result).alternatives).flatMap((row) =>
    rows(row.candidates)
      .map((c) => c.candidate)
      .filter(node),
  );
}
export function products(result?: Envelope): NodeRef[] {
  const values = toolData(result).reached_nodes;
  return (Array.isArray(values) ? values : [])
    .filter(node)
    .filter((n) => n.entity_type === "Product");
}
export async function searchEquipment(query: string, signal: AbortSignal) {
  const filters = query.trim()
    ? [{ name: query.trim() }, { equipment_code: query.trim() }]
    : [{}];
  const replies = await Promise.allSettled(
    filters.map((filter) =>
      direct(
        "search_equipment",
        { filter, page_size: 20, cursor: null },
        signal,
      ),
    ),
  );
  const items = new Map<string, EquipmentCandidate>();
  let more = false;
  const errors: string[] = [];
  for (const reply of replies) {
    if (reply.status === "rejected") {
      errors.push(errorCode(reply.reason));
      continue;
    }
    const data = toolData(reply.value);
    for (const item of rows(data.items))
      if (
        typeof item.equipment_id === "string" &&
        typeof item.equipment_code === "string" &&
        typeof item.equipment_name === "string"
      )
        items.set(item.equipment_id, item as unknown as EquipmentCandidate);
    more ||= data.next_cursor != null;
  }
  return {
    items: [...items.values()].sort(
      (a, b) =>
        a.equipment_code.localeCompare(b.equipment_code) ||
        a.equipment_id.localeCompare(b.equipment_id),
    ),
    more,
    errors,
  };
}
export async function inputs(
  kind: "economic" | "capacity",
  id: string,
  signal: AbortSignal,
) {
  const records: Envelope[] = [];
  let cursor: unknown = null;
  do {
    const response = await request(
      "",
      `/${kind}-inputs/search`,
      { filter: { equipment_id: id }, page_size: 100, cursor },
      signal,
    );
    for (const item of rows(response.data.items)) {
      const key = item[`${kind}_input_id`];
      if (typeof key !== "string") throw new ApiError("INVALID_RESPONSE");
      records.push(
        await request("", `/${kind}-inputs/${key}`, undefined, signal),
      );
    }
    const next = response.data.next_cursor;
    if (next != null && (typeof next !== "string" || next === cursor))
      throw new ApiError("INVALID_RESPONSE");
    cursor = next;
  } while (cursor != null);
  return records;
}
export function displayGraph(
  base: Envelope,
  alternatives: Envelope | undefined,
  metadata: unknown[],
): Envelope {
  const data = toolData(base),
    alt = toolData(alternatives);
  const combined =
    alternatives &&
    generation(base) === generation(alternatives) &&
    alt.graph_sync_state === "CURRENT"
      ? {
          ...data,
          representative_paths: [
            ...rows(data.representative_paths),
            ...rows(alt.representative_paths).filter((path) =>
              rows(path.edges).some(
                (edge) => edge.relation_type === "CAN_SUBSTITUTE",
              ),
            ),
          ],
          targets: [data.target, ...candidates(alternatives)],
        }
      : data;
  return {
    ...base,
    data: {
      tool_results: [
        { tool: rows(base.data.tool_results)[0]?.tool, data: combined },
        ...metadata,
      ],
    },
  };
}
export const keyOf = nodeKey;
