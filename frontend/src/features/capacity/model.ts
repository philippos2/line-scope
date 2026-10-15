import { object, type JsonObject } from "../../api/client";
export type CapacityInput = {
  capacity_input_id: string;
  input_code: string;
  equipment_id: string;
  product_id: string;
  version: number;
  payload: JsonObject;
};
export const rateFields = {
  required_rate: "必要能力",
  normal_rate: "通常能力",
  used_rate: "使用中負荷",
  reserved_rate: "予約負荷",
};
export function blankInput(equipment_id = ""): CapacityInput {
  return {
    capacity_input_id: "",
    input_code: "",
    equipment_id,
    product_id: "",
    version: 0,
    payload: {
      period_start: "",
      period_end: "",
      quantity_unit: "",
      required_rate: null,
      normal_rate: null,
      used_rate: null,
      reserved_rate: null,
      loads_independent: false,
      loads_complete: false,
      compatible: null,
      source: "",
      certainty: "ESTIMATED",
      recovery: null,
    },
  };
}
export function readInput(value: unknown): CapacityInput {
  if (
    !object(value) ||
    !["capacity_input_id", "input_code", "equipment_id", "product_id"].every(
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
    ![
      "period_start",
      "period_end",
      "quantity_unit",
      "source",
      "certainty",
    ].every((key) => typeof p[key] === "string") ||
    !Object.keys(rateFields).every(
      (key) => p[key] === null || typeof p[key] === "string",
    ) ||
    typeof p.loads_independent !== "boolean" ||
    typeof p.loads_complete !== "boolean" ||
    !(p.compatible === null || typeof p.compatible === "boolean")
  )
    throw new Error("INVALID_RESPONSE");
  if (
    p.recovery !== null &&
    (!object(p.recovery) ||
      typeof p.recovery.stopped_at !== "string" ||
      !(p.recovery.buffer === null || typeof p.recovery.buffer === "string") ||
      !["constant_flow", "no_other_allocations", "recovery_meets_demand"].every(
        (key) => object(p.recovery) && typeof p.recovery[key] === "boolean",
      ))
  )
    throw new Error("INVALID_RESPONSE");
  return value as unknown as CapacityInput;
}
