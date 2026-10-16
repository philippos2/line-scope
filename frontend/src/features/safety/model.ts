import { object, type JsonObject } from "../../api/client";
export type SafetyInput = {
  safety_input_id: string;
  input_code: string;
  equipment_id: string;
  version: number;
  payload: JsonObject;
};
export const decisions: Record<string, string> = {
  STOP_REQUIRED: "停止必須",
  CONDITIONAL: "条件付き継続可",
  UNKNOWN: "不明",
};
export const textFields: Record<string, string> = {
  observation: "観測内容",
  criterion: "適用する安全基準",
  conditions: "継続条件",
  risk_notes: "残存リスクの資料・不足情報",
};
export function blankInput(equipment_id = ""): SafetyInput {
  return {
    safety_input_id: "",
    input_code: "",
    equipment_id,
    version: 0,
    payload: {
      period_start: "",
      period_end: "",
      observation: null,
      criterion: null,
      conditions: null,
      risk_notes: null,
      source: "",
      decision: "UNKNOWN",
      certainty: "ESTIMATED",
    },
  };
}
export function readInput(value: unknown): SafetyInput {
  if (
    !object(value) ||
    !["safety_input_id", "input_code", "equipment_id"].every(
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
    !["period_start", "period_end", "source", "decision", "certainty"].every(
      (key) => typeof p[key] === "string",
    ) ||
    !Object.keys(textFields).every(
      (key) => p[key] === null || typeof p[key] === "string",
    ) ||
    !Object.hasOwn(decisions, String(p.decision))
  )
    throw new Error("INVALID_RESPONSE");
  return value as unknown as SafetyInput;
}
