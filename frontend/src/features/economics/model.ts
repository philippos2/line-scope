import { object, type JsonObject } from "../../api/client";

export type CostItem = {
  key: string;
  kind: string;
  amount: string | null;
  hours: string | null;
  independent: boolean;
  source: string;
  certainty: string;
  valid_from: string;
  valid_to: string;
};
export type CostOption = {
  option: string;
  complete: boolean;
  items: CostItem[];
};
export type CostRecovery = {
  daily_operating_hours: string | null;
  constant_daily_operation: boolean | null;
  replacement_removes_degradation: boolean | null;
  source: string;
  certainty: string;
};
export type EconomicInput = {
  economic_input_id: string;
  input_code: string;
  equipment_id: string;
  version: number;
  payload: {
    period_start: string;
    period_end: string;
    operating_hours: string;
    currency: string;
    options: CostOption[];
    cost_recovery?: CostRecovery | null;
  };
};
export const optionNames: Record<string, string> = {
  REPAIR: "修理",
  REPLACE: "交換",
  CONTINUE: "継続",
};
export const kindNames: Record<string, string> = {
  DIRECT: "直接費（JPY）",
  STOPPAGE: "停止損失（JPY/hour）",
  DEGRADATION: "劣化損失（JPY/hour）",
};
export function blankItem(): CostItem {
  return {
    key: "",
    kind: "DIRECT",
    amount: null,
    hours: null,
    independent: false,
    source: "",
    certainty: "ESTIMATED",
    valid_from: "",
    valid_to: "",
  };
}
export function blankInput(equipmentId = ""): EconomicInput {
  return {
    economic_input_id: "",
    input_code: "",
    equipment_id: equipmentId,
    version: 0,
    payload: {
      period_start: "",
      period_end: "",
      operating_hours: "",
      currency: "JPY",
      options: Object.keys(optionNames).map((option) => ({
        option,
        complete: false,
        items: [blankItem()],
      })),
    },
  };
}
export function readInput(value: unknown): EconomicInput {
  if (
    !object(value) ||
    typeof value.economic_input_id !== "string" ||
    typeof value.input_code !== "string" ||
    typeof value.equipment_id !== "string" ||
    typeof value.version !== "number" ||
    !object(value.payload) ||
    !Array.isArray(value.payload.options)
  )
    throw new Error("INVALID_RESPONSE");
  const payload = value.payload;
  if (
    !["period_start", "period_end", "operating_hours", "currency"].every(
      (key) => typeof payload[key] === "string",
    ) ||
    !Number.isSafeInteger(value.version) ||
    value.version < 1 ||
    !Array.isArray(payload.options) ||
    payload.options.length !== 3 ||
    !payload.options.every(
      (option) =>
        object(option) &&
        typeof option.option === "string" &&
        option.option in optionNames &&
        typeof option.complete === "boolean" &&
        Array.isArray(option.items) &&
        option.items.length > 0 &&
        option.items.every(
          (item) =>
            object(item) &&
            [
              "key",
              "kind",
              "source",
              "certainty",
              "valid_from",
              "valid_to",
            ].every((key) => typeof item[key] === "string") &&
            ["amount", "hours"].every(
              (key) => item[key] === null || typeof item[key] === "string",
            ) &&
            typeof item.independent === "boolean",
        ),
    )
  )
    throw new Error("INVALID_RESPONSE");
  if (payload.cost_recovery !== undefined && payload.cost_recovery !== null) {
    const r = payload.cost_recovery;
    if (
      !object(r) ||
      (r.daily_operating_hours !== null &&
        typeof r.daily_operating_hours !== "string") ||
      !["constant_daily_operation", "replacement_removes_degradation"].every(
        (key) => r[key] === null || typeof r[key] === "boolean",
      ) ||
      typeof r.source !== "string" ||
      typeof r.certainty !== "string"
    )
      throw new Error("INVALID_RESPONSE");
  }
  // Preserve server strings; do not recalculate or infer business facts.
  return value as unknown as EconomicInput;
}
export function prepareInput(record: EconomicInput): JsonObject {
  const p = record.payload;
  return {
    input_code: record.input_code,
    equipment_id: record.equipment_id,
    payload: {
      ...p,
      options: p.options.map((option) => ({
        ...option,
        items: option.items.map((item) => ({
          ...item,
          valid_from: item.valid_from || p.period_start,
          valid_to: item.valid_to || p.period_end,
        })),
      })),
    },
  };
}
