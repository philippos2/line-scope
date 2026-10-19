import { object, type JsonObject } from "../../api/client";
import { displayPeriod } from "../investigation/EquipmentInvestigation";
import { inputPeriod } from "../investigation/workspaceModel";

const labels: Record<string, string> = {
  source: "出典",
  certainty: "確度",
  quantity_unit: "数量単位",
  required_rate: "必要能力（毎時）",
  normal_rate: "通常能力（毎時）",
  used_rate: "使用中の能力（毎時）",
  reserved_rate: "予約済み能力（毎時）",
  compatible: "製品の互換性",
  loads_independent: "負荷の独立性",
  loads_complete: "負荷の登録範囲が完全",
  operating_hours: "稼働時間",
  currency: "通貨",
  kind: "種類",
  observation: "観測内容",
  criterion: "判断基準",
  conditions: "適用条件",
  risk_notes: "リスクについての資料",
  decision: "安全判断",
  confirmed: "確認済み",
  work_hours: "作業時間",
  downtime_hours: "停止時間",
  lead_time_hours: "調達待ち時間",
  direct_cost: "直接費用",
  notes: "補足",
  option: "対応案",
  complete: "登録範囲が完全",
  amount: "金額",
  hours: "時間",
  independent: "独立した計上範囲",
  loss_per_hour: "損害額（円／時間）",
  scope_key: "計上範囲",
  product_code: "製品コード",
  valid_from: "適用開始",
  valid_to: "適用終了",
};
const values: Record<string, string> = {
  REPAIR: "修理",
  REPLACE: "交換",
  CONTINUE: "継続使用",
  INTERIM: "暫定対応",
  SUBSTITUTE: "代替",
  DIRECT: "直接費用",
  STOPPAGE: "停止による費用",
  ESTIMATED: "見積もり",
  CONFIRMED: "確認済み",
  CONDITIONAL: "条件付き",
  STOP_REQUIRED: "停止が必要",
  UNKNOWN: "判断できません",
  REPAIR_PLAN: "修理計画",
  REPLACEMENT_PLAN: "交換計画",
  INTERIM_PLAN: "暫定対応計画",
  FAILURE_RECORD: "故障記録",
  REPAIR_RECORD: "修理記録",
};
function text(value: unknown) {
  if (value == null || value === "") return "未登録";
  if (typeof value === "boolean") return value ? "はい" : "いいえ";
  if (typeof value === "string" && /^\d{4}-\d\d-\d\dT/.test(value))
    return displayPeriod(value, value).split("〜")[0];
  return values[String(value)] ?? String(value);
}
function Fields({ payload }: { payload: JsonObject }) {
  return (
    <dl>
      {Object.entries(labels)
        .filter(([key]) => key in payload)
        .map(([key, title]) => (
          <div key={key}>
            <dt>{title}</dt>
            <dd>{text(payload[key])}</dd>
          </div>
        ))}
    </dl>
  );
}
export function ComparisonInputDetails({
  record,
  names = {},
}: {
  record: JsonObject;
  names?: Record<string, string>;
}) {
  const payload = object(record.payload) ? record.payload : {};
  const period = inputPeriod(record);
  return (
    <section aria-label="選択入力の内容">
      <p>
        {names[String(record.equipment_id)] ?? "対象設備の登録入力"}
        {record.product_id
          ? ` ／ ${names[String(record.product_id)] ?? "対象製品"}`
          : ""}
        ・第{String(record.version)}版
      </p>
      {period && <p>適用期間：{displayPeriod(period.start, period.end)}</p>}
      <Fields payload={payload} />
      {(
        [
          ["incident_losses", "製品別の損害額"],
          ["options", "対応案の登録費用"],
          ["items", "費用項目"],
        ] as const
      ).map(([key, title]) =>
        Array.isArray(payload[key]) ? (
          <section key={key}>
            <h4>{title}</h4>
            {(payload[key] as unknown[]).filter(object).map((row, i) => (
              <div key={i}>
                <Fields payload={row} />
                {Array.isArray(row.items) &&
                  row.items
                    .filter(object)
                    .map((item, j) => <Fields key={j} payload={item} />)}
              </div>
            ))}
          </section>
        ) : null,
      )}
      <details>
        <summary>技術情報</summary>
        <pre>{JSON.stringify(record, null, 2)}</pre>
      </details>
    </section>
  );
}
