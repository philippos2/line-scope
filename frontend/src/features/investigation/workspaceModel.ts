import { object, type Envelope, type JsonObject } from "../../api/client";
import { rows } from "./readModel";

export function inputRecord(value: Envelope): JsonObject {
  return object(value.data.input) ? value.data.input : {};
}
export function inputPeriod(record: JsonObject) {
  const p = object(record.payload) ? record.payload : {};
  return typeof p.period_start === "string" && typeof p.period_end === "string"
    ? { start: p.period_start, end: p.period_end }
    : null;
}
export function comparisonPeriod(records: Record<string, JsonObject[]>) {
  const timed = [
    ...(records.economic ?? []),
    ...(records.capacity ?? []),
    ...(records.maintenance ?? []).filter(
      (r) => object(r.payload) && String(r.payload.kind).endsWith("_PLAN"),
    ),
  ];
  const periods = timed.map(inputPeriod);
  if (!periods.length || periods.some((p) => !p))
    return {
      period: null,
      error: "期間を持つ算定データ・能力データ・対応計画を選んでください。",
    };
  const period = periods[0]!;
  if (periods.some((p) => p!.start !== period.start || p!.end !== period.end))
    return {
      period: null,
      error:
        "選択した入力の適用期間が一致しません。入力を選び直すか登録・訂正してください。",
    };
  if (
    (records.safety ?? []).some((r) => {
      const p = inputPeriod(r);
      return !p || p.start > period.start || p.end < period.end;
    })
  )
    return {
      period: null,
      error: "安全条件の適用期間が比較期間全体を覆っていません。",
    };
  return { period, error: "" };
}
export function selectedRecords(
  values: Envelope[],
  ids: string[],
  kind: string,
) {
  return values
    .map(inputRecord)
    .filter((r) => ids.includes(String(r[`${kind}_input_id`])));
}
export function comparisonOptions(result?: Envelope) {
  const pkg = object(result?.data.decision_package)
    ? result.data.decision_package
    : {};
  return rows(object(pkg.comparison) ? pkg.comparison.options : []);
}
