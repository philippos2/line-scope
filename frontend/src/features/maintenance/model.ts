import { object, type JsonObject } from "../../api/client";
export type MaintenanceInput = {
  maintenance_input_id: string;
  input_code: string;
  equipment_id: string;
  version: number;
  payload: JsonObject;
};
export const kinds: Record<string, string> = {
  REPAIR_PLAN: "修理案",
  REPLACEMENT_PLAN: "交換案",
  INTERIM_PLAN: "暫定対応案",
  FAILURE_RECORD: "故障履歴",
  REPAIR_RECORD: "修理履歴",
};
export const fields: Record<string, string> = {
  details: "計画・事象の内容",
  risk_notes: "残存リスクの資料・不足情報",
  maintenance_plan_id: "関連する保全予定ID（任意）",
  lead_time_hours: "調達待ち（時間）",
  work_hours: "作業時間（時間）",
  downtime_hours: "停止時間（時間）",
  direct_cost_jpy: "交換費を除く直接費（JPY）",
  replacement_cost_jpy: "評価期間に算入する交換費（JPY）",
  past_loss_jpy: "過去停止損失（JPY・履歴のみ）",
  interim_until: "暫定対応の終了日時",
};
export function blankInput(equipment_id = ""): MaintenanceInput {
  return {
    maintenance_input_id: "",
    input_code: "",
    equipment_id,
    version: 0,
    payload: {
      kind: "REPAIR_PLAN",
      period_start: "",
      period_end: "",
      source: "",
      details: "",
      risk_notes: null,
      maintenance_plan_id: null,
      lead_time_hours: null,
      work_hours: null,
      downtime_hours: null,
      direct_cost_jpy: null,
      replacement_cost_jpy: null,
      past_loss_jpy: null,
      interim_until: null,
      include_replacement_cost: null,
    },
  };
}
export function readInput(value: unknown): MaintenanceInput {
  if (
    !object(value) ||
    !["maintenance_input_id", "input_code", "equipment_id"].every(
      (key) => typeof value[key] === "string",
    ) ||
    typeof value.version !== "number" ||
    !Number.isSafeInteger(value.version) ||
    value.version < 1 ||
    !object(value.payload)
  )
    throw new Error("INVALID_RESPONSE");
  const p = value.payload;
  if (
    !["period_start", "period_end", "source", "details", "kind"].every(
      (key) => typeof p[key] === "string",
    ) ||
    !Object.hasOwn(kinds, String(p.kind)) ||
    !Object.keys(fields).every(
      (key) => p[key] === null || typeof p[key] === "string",
    ) ||
    !(
      p.include_replacement_cost === null ||
      typeof p.include_replacement_cost === "boolean"
    )
  )
    throw new Error("INVALID_RESPONSE");
  return value as unknown as MaintenanceInput;
}
